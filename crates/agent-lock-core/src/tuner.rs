//! The tuner: turns a manifest into an `hpm.lock`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde_json::json;

use crate::adapters::{HarnessAdapter, ReferenceAdapter};
use crate::error::{Error, Result};
use crate::lockfile::{Context, Decision, Evidence, Harness, Instructions, LLM, Lockfile, Policy, Provenance, Skill, Tool, Verify};
use crate::manifest::{HarnessCandidate, Manifest};
use crate::search::{select_winner, Stack, StackScore, TrialResult};
use crate::store::Store;
use crate::tasks::TaskPack;

/// Aggregated metrics container produced by the tuner.

pub struct Tuner {
    pub manifest: Manifest,
    pub workdir: PathBuf,
    pub store: Store,
    pack_by_task: BTreeMap<String, crate::tasks::TaskPack>,
    adapter: ReferenceAdapter,
}

impl Tuner {
    pub fn new(manifest: Manifest, workdir: impl Into<PathBuf>) -> Self {
        let workdir: PathBuf = workdir.into();
        let store = Store::new(workdir.join("store"));
        Tuner {
            manifest,
            workdir,
            store,
            pack_by_task: BTreeMap::new(),
            adapter: ReferenceAdapter::default(),
        }
    }

    /// Load the manifest's task packs and return the search-split tasks.
    pub fn load_packs(&mut self) -> Vec<crate::tasks::Task> {
        let mut search: Vec<crate::tasks::Task> = Vec::new();
        let base = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        for ref_ in self.manifest.task_packs() {
            match TaskPack::load(&ref_, Some(&base)) {
                Ok(pack) => {
                    let (s, _h) = pack.split(self.manifest.search_frac(), self.manifest.budget.random_seed);
                    for t in pach_tasks(&pack) {
                        self.pack_by_task.insert(t.id.clone(), pack.clone());
                    }
                    search.extend(s);
                }
                Err(e) => eprintln!("warn: skipping task pack {ref_}: {e}"),
            }
        }
        search
    }

    /// Cartesian product over the manifest's candidate axes.
    pub fn enumerate_stacks(&self) -> Vec<Stack> {
        let c = &self.manifest.candidates;
        let llm_combos = llm_combos(&c.llm);
        let decisions = if c.decision.is_empty() {
            vec!["none".to_string()]
        } else {
            c.decision.clone()
        };
        let harnesses = harness_combos(&c.harness);

        let mut stacks = Vec::new();
        for llm in &llm_combos {
            for decision in &decisions {
                for (harness, pattern) in &harnesses {
                    stacks.push(Stack {
                        llm: llm.clone(),
                        harness: harness.clone(),
                        pattern: pattern.clone(),
                        decision: decision.clone(),
                        tools: self.manifest.tools.keys().cloned().collect(),
                        skills: self.manifest.skills.keys().cloned().collect(),
                        instructions: instructions_files(&self.manifest.instructions),
                        max_steps: 40,
                        max_cost_usd_per_task: None,
                        retries: policy_axis(&self.manifest.candidates.policy, "retries", 0),
                        temperature: policy_axis_float(&self.manifest.candidates.policy, "temperature"),
                    });
                }
            }
        }
        if stacks.len() > 200 {
            stacks.truncate(200);
        }
        stacks
    }

    /// Run one trial (copying fixtures, running the harness, grading).
    pub fn run_trial(&self, stack: &Stack, task: &crate::tasks::Task, seed: u64, ws_root: &Path) -> TrialResult {
        let ws = ws_root.join(format!("{}_{}_{}", &stack.hash()[..10.min(stack.hash().len())], task.id, seed));
        let _ = std::fs::remove_dir_all(&ws);
        let _ = std::fs::create_dir_all(&ws);

        let outcome = self.adapter.run(stack, task, &ws, seed).unwrap_or_else(|_| {
            crate::adapters::RunOutcome {
                success: false,
                cost_usd: 0.0,
                latency_s: 0.0,
                steps: 0,
                trace: json!([]),
            }
        });
        let grades = self
            .pack_by_task
            .get(&task.id)
            .map(|p| p.grade(task, &ws))
            .unwrap_or_default();
        let success = outcome.success && grades.iter().all(|g| g.success);
        let score = grades.iter().map(|g| g.score).sum::<f64>() / grades.len().max(1) as f64;

        // persist the trace to the store (content-addressed)
        let trace = json!({
            "trial": {"stack": stack.hash(), "task": task.id, "seed": seed},
            "events": outcome.trace,
            "result": {"artifacts": task.expected_artifacts()},
            "metrics": {"steps": outcome.steps, "cost_usd": outcome.cost_usd, "latency_s": outcome.latency_s},
            "grades": grades.iter().map(|g| json!({"success": g.success, "score": g.score})).collect::<Vec<_>>(),
        });
        let _ = self.store.put_value(&trace);

        TrialResult {
            stack_hash: stack.hash(),
            task_id: task.id.clone(),
            seed,
            success,
            score,
            cost_usd: outcome.cost_usd,
            latency_s: outcome.latency_s,
            steps: outcome.steps,
        }
    }

    /// Tune: enumerate, run, aggregate, select, and write `hpm.lock`.
    pub fn tune(&mut self) -> Result<Lockfile> {
        let search_tasks = self.load_packs();
        let stacks = self.enumerate_stacks();
        let seeds = self.manifest.seeds();
        let ws_root = self.workdir.join("runs");
        let _ = std::fs::create_dir_all(&ws_root);

        let mut results_by_stack: BTreeMap<String, Vec<TrialResult>> = BTreeMap::new();
        for stack in &stacks {
            for task in &search_tasks {
                for seed in 0..seeds {
                    let tr = self.run_trial(stack, task, seed, &ws_root);
                    results_by_stack.entry(stack.hash()).or_default().push(tr);
                }
            }
        }
        // respect max-trials globally
        let mut n = 0usize;
        let max = self.manifest.budget.max_trials.unwrap_or(usize::MAX);
        for v in results_by_stack.values_mut() {
            if n >= max {
                v.clear();
            } else {
                v.truncate(max.saturating_sub(n));
                n += v.len();
            }
        }

        let mut scores: Vec<StackScore> = Vec::new();
        for stack in &stacks {
            if let Some(trials) = results_by_stack.get(&stack.hash()) {
                if !trials.is_empty() {
                    scores.push(StackScore {
                        stack: stack.clone(),
                        trials: trials.clone(),
                        n: trials.len(),
                    });
                }
            }
        }

        let winner = select_winner(
            scores.clone(),
            &self.manifest.objective.primary,
            &self.manifest.objective.constraints,
            &self.manifest.objective.select,
        )
        .ok_or_else(|| Error::Tuning("no viable stack found".into()))?;

        let lock = self.build_lock(&winner, &scores);
        lock.save(std::path::Path::new(crate::LOCKFILE_PATH))?;
        let _ = self.write_report(&lock, &scores);
        Ok(lock)
    }

    fn build_lock(&self, winner: &StackScore, _scores: &[StackScore]) -> Lockfile {
        let s = &winner.stack;
        let llms = s
            .llm
            .iter()
            .map(|(role, spec)| {
                let (provider, model) = match spec.split_once(':') {
                    Some((p, m)) if !m.is_empty() => (p.to_string(), m.to_string()),
                    _ => ("reference".to_string(), spec.clone()),
                };
                LLM {
                    role: role.clone(),
                    provider,
                    model,
                    resolved_from: Some(spec.clone()),
                    params: BTreeMap::new(),
                    fingerprint: Some(format!("sha256:{}", crate::hash::sha256_hex(spec.as_bytes()))),
                }
            })
            .collect();

        let mut success_rate = BTreeMap::new();
        success_rate.insert("mean".to_string(), roundf(winner.success_rate()));
        let mut cost = BTreeMap::new();
        cost.insert("mean".to_string(), roundf(winner.mean_cost()));
        let mut latency = BTreeMap::new();
        latency.insert("p50".to_string(), roundf(winner.mean_latency()));
        latency.insert("p95".to_string(), roundf(winner.p95_latency()));

        let mut stack_map = BTreeMap::new();
        stack_map.insert("name".to_string(), serde_json::json!(self.manifest.name()));
        stack_map.insert("selection".to_string(), serde_json::json!(self.manifest.objective.select));
        let mut search_map = BTreeMap::new();
        search_map.insert("strategy".to_string(), serde_json::json!(self.manifest.budget.strategy));
        search_map.insert("candidates".to_string(), serde_json::json!(winner.n));

        Lockfile {
            manifest_hash: Some(self.manifest.manifest_hash()),
            stack: stack_map,
            llm: llms,
            decision: Decision {
                kind: s.decision.clone(),
                decisions: if s.decision == "none" { vec![] } else { vec!["retry".into(), "stop".into()] },
                ..Default::default()
            },
            harness: Harness {
                name: s.harness.clone(),
                pattern: Some(s.pattern.clone()),
                ..Default::default()
            },
            tool: s.tools.iter().map(|t| Tool { name: t.clone(), kind: "builtin".into(), ..Default::default() }).collect(),
            skill: s.skills.iter().map(|sk| Skill { name: sk.clone(), origin: "first-party".into(), editable: true, evidence_digest: Some(String::new()), ..Default::default() }).collect(),
            instructions: s.instructions.iter().map(|i| Instructions { name: i.clone(), scope: "project".into(), ..Default::default() }).collect(),
            policy: Policy {
                retries: 1,
                max_steps: 40,
                human_approval: "never".into(),
                ..Default::default()
            },
            context: Context { isolation: self.manifest.context.get("isolation").and_then(serde_json::Value::as_str).unwrap_or("locked-only").into(), ..Default::default() },
            evidence: Evidence {
                task_pack: Some(self.manifest.task_packs().join(",")),
                split: "search".into(),
                trials: winner.n,
                success_rate,
                cost_usd_per_task: cost,
                latency_s_per_task: latency,
                ..Default::default()
            },
            verify: Verify::default(),
            provenance: Provenance {
                backend: self.manifest.backend_target(),
                search: search_map,
                ..Default::default()
            },
            ..Default::default()
        }
    }

    fn write_report(&self, lock: &Lockfile, _scores: &[StackScore]) -> Result<()> {
        let report = self.workdir.join("report.md");
        std::fs::write(&report, format!("# agent-lock report\n\n{}\n", lock.summary()))?;
        Ok(())
    }
}

fn roundf(v: f64) -> f64 {
    (v * 1e4).round() / 1e4
}

fn pach_tasks(pack: &TaskPack) -> Vec<crate::tasks::Task> {
    pack.tasks.clone()
}

fn llm_combos(cands: &BTreeMap<String, crate::manifest::LLMCandidate>) -> Vec<BTreeMap<String, String>> {
    if cands.is_empty() {
        let mut m = BTreeMap::new();
        m.insert("planner".to_string(), "reference:qwen-7b".to_string());
        return vec![m];
    }
    let roles: Vec<String> = cands.keys().cloned().collect();
    let mut per_role: Vec<Vec<(String, String)>> = Vec::new();
    for role in &roles {
        let opts = cands.get(role).map(|c| c.any_of.clone()).unwrap_or_default();
        let opts = if opts.is_empty() {
            vec!["reference:qwen-7b".to_string()]
        } else {
            opts
        };
        per_role.push(opts.into_iter().map(|o| (role.clone(), o)).collect());
    }
    // cartesian product
    let mut combos: Vec<BTreeMap<String, String>> = vec![BTreeMap::new()];
    for options in per_role {
        let mut next = Vec::new();
        for c in &combos {
            for (role, model) in &options {
                let mut cc = c.clone();
                cc.insert(role.clone(), model.clone());
                next.push(cc);
            }
        }
        combos = next;
    }
    combos
}

fn harness_combos(cands: &[HarnessCandidate]) -> Vec<(String, String)> {
    if cands.is_empty() {
        return vec![("reference".to_string(), "single-agent".to_string())];
    }
    let mut out = Vec::new();
    for h in cands {
        let patterns = if h.pattern.is_empty() { vec!["single-agent".to_string()] } else { h.pattern.clone() };
        for p in patterns {
            out.push((h.name.clone(), p));
        }
    }
    out
}

fn instructions_files(ins: &BTreeMap<String, serde_json::Value>) -> Vec<String> {
    ins.get("files")
        .and_then(serde_json::Value::as_array)
        .map(|a| a.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default()
}

fn policy_axis(policy: &BTreeMap<String, Vec<serde_json::Value>>, key: &str, default: u32) -> u32 {
    policy
        .get(key)
        .and_then(|v| v.first())
        .and_then(serde_json::Value::as_u64)
        .map(|n| n as u32)
        .unwrap_or(default)
}

fn policy_axis_float(policy: &BTreeMap<String, Vec<serde_json::Value>>, key: &str) -> Option<f64> {
    policy
        .get(key)
        .and_then(|v| v.first())
        .and_then(serde_json::Value::as_f64)
}
