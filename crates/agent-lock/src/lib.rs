//! PyO3 Python bindings for **agent-lock**.
//!
//! Exposes the same user-facing API as the (reference) pure-Python `agent_lock`
//! package, backed by the Rust core (`agent-lock-core`): `Manifest`,
//! `SearchSpace`, `Objective`, `Budget`, `lock()`, `load()`, and the `Lockfile`
//! model.
//!
//! Dict-shaped data is exchanged as canonical JSON strings to keep the binding
//! surface small and robust.

use std::path::{Path, PathBuf};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use agent_lock_core as core;

fn py_err(e: core::Error) -> PyErr {
    PyValueError::new_err(e.to_string())
}

// --------------------------------------------------------------------------- //
// Manifest
// --------------------------------------------------------------------------- //
/// A parsed `hpm.toml`.
#[pyclass(module = "agent_lock", name = "Manifest")]
#[derive(Clone)]
pub struct PyManifest {
    inner: core::Manifest,
}

#[pymethods]
impl PyManifest {
    #[staticmethod]
    fn load(path: &str) -> PyResult<PyManifest> {
        core::Manifest::load(Path::new(path)).map(|inner| PyManifest { inner }).map_err(py_err)
    }

    #[staticmethod]
    fn from_str(source: &str) -> PyResult<PyManifest> {
        core::Manifest::from_str(source).map(|inner| PyManifest { inner }).map_err(py_err)
    }

    #[getter]
    fn name(&self) -> String {
        self.inner.name()
    }

    #[getter]
    fn backend(&self) -> String {
        self.inner.backend_target()
    }

    fn manifest_hash(&self) -> String {
        self.inner.manifest_hash()
    }

    fn task_packs(&self) -> Vec<String> {
        self.inner.task_packs()
    }

    fn to_json(&self) -> String {
        serde_json::to_string(&self.inner.tasks).unwrap_or_default()
    }
}

// --------------------------------------------------------------------------- //
// Objective / Budget
// --------------------------------------------------------------------------- //
#[pyclass(module = "agent_lock", name = "Objective")]
#[derive(Clone)]
pub struct PyObjective {
    primary: String,
    constraints: std::collections::BTreeMap<String, String>,
    select: String,
}

#[pymethods]
impl PyObjective {
    #[new]
    #[pyo3(signature = (primary="success-rate".to_string(), select="min-cost".to_string(), constraints=None))]
    fn new(
        primary: String,
        select: String,
        constraints: Option<std::collections::BTreeMap<String, String>>,
    ) -> Self {
        PyObjective {
            primary,
            constraints: constraints.unwrap_or_default(),
            select,
        }
    }

    #[getter]
    fn primary(&self) -> String {
        self.primary.clone()
    }
    #[getter]
    fn select(&self) -> String {
        self.select.clone()
    }
    #[getter]
    fn constraints(&self) -> String {
        serde_json::to_string(&self.constraints).unwrap_or_default()
    }
}

#[pyclass(module = "agent_lock", name = "Budget")]
#[derive(Clone)]
pub struct PyBudget {
    max_spend_usd: Option<f64>,
    max_trials: Option<usize>,
    strategy: String,
    random_seed: u64,
}

#[pymethods]
impl PyBudget {
    #[new]
    #[pyo3(signature = (max_spend_usd=None, max_trials=None, strategy="grid".to_string(), random_seed=0))]
    fn new(max_spend_usd: Option<f64>, max_trials: Option<usize>, strategy: String, random_seed: u64) -> Self {
        PyBudget {
            max_spend_usd,
            max_trials,
            strategy,
            random_seed,
        }
    }
}

impl PyBudget {
    pub(crate) fn to_core(&self) -> core::manifest::Budget {
        core::manifest::Budget {
            max_spend_usd: self.max_spend_usd,
            max_trials: self.max_trials,
            strategy: self.strategy.clone(),
            random_seed: self.random_seed,
        }
    }
}

// --------------------------------------------------------------------------- //
// SearchSpace
// --------------------------------------------------------------------------- //
#[pyclass(module = "agent_lock", name = "SearchSpace")]
#[derive(Clone)]
pub struct PySearchSpace {
    llm: std::collections::BTreeMap<String, Vec<String>>,
    decision: Vec<String>,
    harness: Vec<String>,
    policy: serde_json::Value,
    tools: serde_json::Value,
    skills: serde_json::Value,
    tasks: serde_json::Value,
    objective: Option<PyObjective>,
    budget: Option<PyBudget>,
}

fn default_tasks() -> serde_json::Value {
    serde_json::json!({"seeds": 2})
}

#[pymethods]
impl PySearchSpace {
    #[new]
    #[pyo3(signature = (llm=None, decision=None, harness=None, policy=None, tools=None, skills=None, objective=None, budget=None, tasks=None))]
    fn new(
        llm: Option<std::collections::BTreeMap<String, Vec<String>>>,
        decision: Option<Vec<String>>,
        harness: Option<Vec<String>>,
        policy: Option<String>,
        tools: Option<String>,
        skills: Option<String>,
        objective: Option<PyObjective>,
        budget: Option<PyBudget>,
        tasks: Option<String>,
    ) -> Self {
        let parse = |s: Option<String>, fallback: serde_json::Value| -> serde_json::Value {
            match s {
                Some(txt) => serde_json::from_str(&txt).unwrap_or(fallback),
                None => fallback,
            }
        };
        PySearchSpace {
            llm: llm.unwrap_or_default(),
            decision: decision.unwrap_or_default(),
            harness: harness.unwrap_or_default(),
            policy: parse(policy, serde_json::json!({})),
            tools: parse(tools, serde_json::json!({})),
            skills: parse(skills, serde_json::json!({})),
            tasks: parse(tasks, default_tasks()),
            objective,
            budget,
        }
    }

    fn to_manifest(&self, name: &str) -> PyManifest {
        let m = to_core_manifest(name, self);
        PyManifest { inner: m }
    }
}

fn to_core_manifest(name: &str, sp: &PySearchSpace) -> core::Manifest {
    let mut candidates = core::manifest::Candidates::default();
    candidates.llm = sp
        .llm
        .iter()
        .map(|(k, v)| (k.clone(), core::manifest::LLMCandidate { any_of: v.clone() }))
        .collect();
    candidates.decision = sp.decision.clone();
    candidates.harness = sp
        .harness
        .iter()
        .map(|h| core::manifest::HarnessCandidate {
            name: h.clone(),
            pattern: vec![],
            config: Default::default(),
        })
        .collect();
    candidates.policy = match &sp.policy {
        serde_json::Value::Object(map) => map
            .iter()
            .map(|(k, v)| {
                let list = match v {
                    serde_json::Value::Array(a) => a.clone(),
                    other => vec![other.clone()],
                };
                (k.clone(), list)
            })
            .collect(),
        _ => Default::default(),
    };

    let objective = match &sp.objective {
        Some(o) => core::manifest::Objective {
            primary: o.primary.clone(),
            constraints: o.constraints.clone(),
            select: o.select.clone(),
        },
        None => core::manifest::Objective::default(),
    };
    let budget = sp
        .budget
        .as_ref()
        .map(|b| b.to_core())
        .unwrap_or_else(core::manifest::Budget::default);

    let mut project = std::collections::BTreeMap::new();
    project.insert("name".into(), serde_json::json!(name));
    core::Manifest {
        project,
        tasks: object_of(&sp.tasks),
        candidates,
        tools: object_of(&sp.tools),
        skills: object_of(&sp.skills),
        objective,
        budget,
        ..Default::default()
    }
}

fn object_of(v: &serde_json::Value) -> std::collections::BTreeMap<String, serde_json::Value> {
    match v {
        serde_json::Value::Object(map) => map
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
        _ => Default::default(),
    }
}

// --------------------------------------------------------------------------- //
// Lockfile
// --------------------------------------------------------------------------- //
#[pyclass(module = "agent_lock", name = "Lockfile")]
pub struct PyLockfile {
    inner: core::Lockfile,
}

#[pymethods]
impl PyLockfile {
    #[staticmethod]
    fn load(path: &str) -> PyResult<PyLockfile> {
        core::Lockfile::load(Path::new(path)).map(|inner| PyLockfile { inner }).map_err(py_err)
    }

    fn summary(&self) -> String {
        self.inner.summary()
    }

    fn to_json(&self) -> String {
        serde_json::to_string(&self.inner).unwrap_or_default()
    }

    #[getter]
    fn manifest_hash(&self) -> Option<String> {
        self.inner.manifest_hash.clone()
    }

    #[getter]
    fn harness(&self) -> String {
        self.inner.harness.name.clone()
    }

    #[getter]
    fn decision(&self) -> String {
        self.inner.decision.kind.clone()
    }

    #[getter]
    fn llm(&self) -> String {
        let pairs: Vec<(String, String)> = self
            .inner
            .llm
            .iter()
            .map(|l| (l.role.clone(), format!("{}:{}", l.provider, l.model)))
            .collect();
        serde_json::to_string(&pairs).unwrap_or_else(|_| "[]".into())
    }

    #[getter]
    fn evidence(&self) -> String {
        let mut m = serde_json::Map::new();
        m.insert("trials".into(), serde_json::json!(self.inner.evidence.trials));
        m.insert(
            "success_rate".into(),
            serde_json::json!(self.inner.evidence.success_rate),
        );
        m.insert(
            "cost_usd_per_task".into(),
            serde_json::json!(self.inner.evidence.cost_usd_per_task),
        );
        m.insert(
            "latency_s_per_task".into(),
            serde_json::json!(self.inner.evidence.latency_s_per_task),
        );
        serde_json::to_string(&serde_json::Value::Object(m)).unwrap_or_else(|_| "{}".into())
    }

    #[getter]
    fn provenance(&self) -> String {
        self.inner.provenance.backend.clone()
    }
}

// --------------------------------------------------------------------------- //
// LockedAgent
// --------------------------------------------------------------------------- //
#[pyclass(module = "agent_lock", name = "LockedAgent")]
pub struct PyLockedAgent {
    lock: core::Lockfile,
}

#[pymethods]
impl PyLockedAgent {
    fn summary(&self) -> String {
        self.lock.summary()
    }

    /// Run the locked agent on a prompt using the Rust reference harness.
    /// Returns a JSON object with `success` / `model` / `cost_usd`.
    fn run(&self, prompt: &str) -> String {
        let model = self
            .lock
            .llm
            .first()
            .map(|l| l.model.clone())
            .unwrap_or_else(|| "qwen-7b".into());
        let provider = core::providers::ReferenceProvider::default();
        let r = provider.complete(&model, prompt.len() as u64);
        serde_json::json!({
            "success": r.content.starts_with("ANSWER_OK"),
            "model": model,
            "cost_usd": r.cost_usd,
        })
        .to_string()
    }
}

// --------------------------------------------------------------------------- //
// module functions
// --------------------------------------------------------------------------- //
#[pyfunction]
#[pyo3(signature = (manifest=None, backend=None, workdir=None))]
fn lock(py: Python<'_>, manifest: Option<PyObject>, backend: Option<String>, workdir: Option<String>) -> PyResult<PyLockfile> {
    let core_manifest = resolve_manifest(py, manifest, backend.as_deref())?;
    let wd = workdir.unwrap_or_else(|| ".agentlock".to_string());
    let mut tuner = core::Tuner::new(core_manifest, &wd);
    let lf = tuner.tune().map_err(py_err)?;
    Ok(PyLockfile { inner: lf })
}

#[pyfunction]
fn load(path: &str) -> PyResult<PyLockedAgent> {
    core::Lockfile::load(Path::new(path))
        .map(|lock| PyLockedAgent { lock })
        .map_err(py_err)
}

fn resolve_manifest(py: Python<'_>, manifest: Option<PyObject>, backend: Option<&str>) -> PyResult<core::Manifest> {
    let mut m: core::Manifest = match manifest {
        Some(obj) => {
            if let Ok(pm) = obj.extract::<PyRef<PyManifest>>(py) {
                pm.inner.clone()
            } else if let Ok(sp) = obj.extract::<PyRef<PySearchSpace>>(py) {
                to_core_manifest("agent", &sp)
            } else if let Ok(s) = obj.extract::<String>(py) {
                // Accept either a path or raw TOML text.
                let p = Path::new(&s);
                if p.exists() {
                    core::Manifest::load(p).map_err(py_err)?
                } else {
                    core::Manifest::from_str(&s).map_err(py_err)?
                }
            } else {
                return Err(PyValueError::new_err(
                    "manifest must be a al.Manifest, al.SearchSpace, a path, or TOML text",
                ));
            }
        }
        None => core::Manifest::load(Path::new("hpm.toml")).map_err(py_err)?,
    };
    if let Some(b) = backend {
        m.backend.insert("target".to_string(), serde_json::json!(b));
    }
    Ok(m)
}

#[pyfunction]
#[pyo3(signature = (manifest=None, to=None, all=false, apply=false, rollback=false, force=false, workdir=None))]
fn upgrade(
    py: Python<'_>,
    manifest: Option<PyObject>,
    to: Option<String>,
    all: bool,
    apply: bool,
    rollback: bool,
    force: bool,
    workdir: Option<String>,
) -> PyResult<String> {
    let m = resolve_manifest(py, manifest, None)?;
    let spec = core::ops::UpgradeSpec {
        to,
        all,
        apply,
        rollback,
        force,
        workdir: PathBuf::from(workdir.unwrap_or_else(|| ".agentlock".to_string())),
    };
    let o = core::ops::upgrade(m, &spec).map_err(py_err)?;
    Ok(serde_json::json!({
        "plan": o.plan,
        "applied": o.applied,
        "rolled_back": o.rolled_back,
        "before": o.before,
        "after": o.after,
        "lock_path": o.lock_path.to_string_lossy(),
        "message": o.message,
    })
    .to_string())
}

#[pyfunction]
#[pyo3(signature = (manifest=None, depth="auto".to_string(), data="user".to_string(), harness=None, out=None, strict=false, apply=false, max_trials=None, workdir=None))]
fn optimize(
    py: Python<'_>,
    manifest: Option<PyObject>,
    depth: String,
    data: String,
    harness: Option<String>,
    out: Option<String>,
    strict: bool,
    apply: bool,
    max_trials: Option<usize>,
    workdir: Option<String>,
) -> PyResult<String> {
    let m = resolve_manifest(py, manifest, None)?;
    let spec = core::ops::OptimizeSpec {
        depth,
        data,
        harness,
        out: PathBuf::from(out.unwrap_or_else(|| "harness.opt.lock".to_string())),
        strict,
        apply,
        max_trials,
        workdir: PathBuf::from(workdir.unwrap_or_else(|| ".agentlock".to_string())),
    };
    let o = core::ops::optimize(m, &spec).map_err(py_err)?;
    Ok(serde_json::json!({
        "path": o.path.to_string_lossy(),
        "report": o.report,
        "summary": o.lock.summary(),
    })
    .to_string())
}

#[pymodule]
fn _agent_lock(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyManifest>()?;
    m.add_class::<PyObjective>()?;
    m.add_class::<PyBudget>()?;
    m.add_class::<PySearchSpace>()?;
    m.add_class::<PyLockfile>()?;
    m.add_class::<PyLockedAgent>()?;
    m.add_function(wrap_pyfunction!(lock, m)?)?;
    m.add_function(wrap_pyfunction!(load, m)?)?;
    m.add_function(wrap_pyfunction!(upgrade, m)?)?;
    m.add_function(wrap_pyfunction!(optimize, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("LOCK_VERSION", core::LOCK_VERSION)?;
    Ok(())
}
