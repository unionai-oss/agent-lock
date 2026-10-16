//! Task packs.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct Task {
    pub id: String,
    pub prompt: String,
    pub fixtures: Option<PathBuf>,
    #[serde(default)]
    pub tools: Vec<String>,
    #[serde(default)]
    pub expected: BTreeMap<String, serde_json::Value>,
    #[serde(default)]
    pub graders: Vec<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(rename = "timeout-seconds", default = "default_timeout")]
    pub timeout_seconds: u64,
    #[serde(skip)]
    pub prompt_text: String,
    #[serde(skip)]
    pub pack_dir: Option<PathBuf>,
}

fn default_timeout() -> u64 {
    600
}

impl Task {
    pub fn expected_artifacts(&self) -> Vec<String> {
        self.expected
            .get("artifacts")
            .and_then(serde_json::Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default()
    }

    pub fn load_prompt_text(&mut self) {
        if !self.prompt_text.is_empty() {
            return;
        }
        if let (Some(dir), false) = (&self.pack_dir, self.prompt.is_empty()) {
            let p = dir.join(&self.prompt);
            if let Ok(t) = std::fs::read_to_string(&p) {
                self.prompt_text = t;
            }
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct PackHeader {
    pub name: String,
    pub version: String,
    pub domain: String,
    pub license: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct PackFile {
    pub pack: PackHeader,
    pub task: Vec<Task>,
}

#[derive(Debug, Clone)]
pub struct TaskPack {
    pub name: String,
    pub version: String,
    pub domain: String,
    pub path: PathBuf,
    pub hash: String,
    pub tasks: Vec<Task>,
}

#[derive(Debug, Clone)]
pub struct Grade {
    pub grader: String,
    pub success: bool,
    pub score: f64,
}

impl TaskPack {
    pub fn load(source: &str, base: Option<&Path>) -> Result<TaskPack> {
        let p = PathBuf::from(source);
        let p = if p.is_absolute() {
            p
        } else if let Some(b) = base {
            b.join(&p)
        } else {
            p
        };
        let pack_path = p.join("pack.toml");
        let text = std::fs::read_to_string(&pack_path)
            .map_err(|e| Error::TaskPack(format!("missing pack.toml at {}: {e}", p.display())))?;
        let file: PackFile = toml::from_str(&text)
            .map_err(|e| Error::TaskPack(format!("invalid pack.toml: {e}")))?;
        let mut tasks = file.task;
        for t in tasks.iter_mut() {
            t.pack_dir = Some(p.clone());
            t.load_prompt_text();
        }
        let hash = crate::hash::sha256_hex(text.as_bytes());
        Ok(TaskPack {
            name: file.pack.name,
            version: file.pack.version,
            domain: file.pack.domain,
            path: p,
            hash,
            tasks,
        })
    }

    /// Deterministic search/holdout split over task ids.
    pub fn split(&self, search_frac: f64, seed: u64) -> (Vec<Task>, Vec<Task>) {
        let mut tasks: Vec<&Task> = self.tasks.iter().collect();
        tasks.sort_by(|a, b| a.id.cmp(&b.id));
        let n_search = ((tasks.len() as f64) * search_frac).round().max(1.0) as usize;
        let mut idx: Vec<usize> = (0..tasks.len()).collect();
        // xorshift-ish deterministic shuffle from seed
        let mut state = seed;
        for i in (1..idx.len()).rev() {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            let j = (state as usize) % (i + 1);
            idx.swap(i, j);
        }
        let search: Vec<Task> = idx[..n_search].iter().map(|&i| tasks[i].clone()).collect();
        let holdout: Vec<Task> = idx[n_search..].iter().map(|&i| tasks[i].clone()).collect();
        (search, holdout)
    }

    /// Grade a task against its workspace. v0.1 uses artifact checks by default.
    pub fn grade(&self, task: &Task, workspace: &Path) -> Vec<Grade> {
        let expected = task.expected_artifacts();
        if task.graders.is_empty() || task.graders.iter().all(|g| g.starts_with("artifact:")) {
            let missing: Vec<String> = expected
                .iter()
                .filter(|a| !workspace.join(a).exists())
                .cloned()
                .collect();
            let success = missing.is_empty();
            return vec![Grade {
                grader: format!("artifact:{}", expected.join(",")),
                success,
                score: if success { 1.0 } else { 0.0 },
            }];
        }
        // For v0.1 the only supported extra grader type is "tests:" which we
        // treat as a failed grade unless an artifact check passes too. This
        // mirrors the reference (deterministic) grader set.
        let expected_ok = expected.iter().all(|a| workspace.join(a).exists());
        vec![Grade {
            grader: "tests:check".into(),
            success: expected_ok,
            score: if expected_ok { 1.0 } else { 0.0 },
        }]
    }
}
