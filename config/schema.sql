PRAGMA foreign_keys = ON;
CREATE TABLE seen_sources (
 source_id TEXT PRIMARY KEY, first_seen_at TEXT,
 aliases_json TEXT CHECK(aliases_json IS NULL OR json_valid(aliases_json)),
 document_version TEXT, processed_at TEXT
);
CREATE TABLE search_log (
 log_id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, keyword TEXT,
 layer TEXT CHECK(layer IN ('layer1','layer2','layer3')),
 result TEXT CHECK(result IN ('cache_hit','excluded','opened','opened_metadata_only','open_failed','checkpoint','review')),
 case_id TEXT, token_cost INTEGER, timestamp TEXT,
 run_id TEXT, batch_id TEXT, opened_at TEXT, document_version TEXT,
 document_url TEXT, content_sha256 TEXT, details_json TEXT CHECK(details_json IS NULL OR json_valid(details_json))
);
CREATE TABLE cases (
 case_id TEXT PRIMARY KEY, phase_found TEXT, status TEXT, last_updated TEXT,
 -- Derived from authoritative attribution_checks; recompute on import/audit, never edit independently.
 human_audit_status TEXT NOT NULL DEFAULT 'unverified' CHECK(human_audit_status IN
   ('not_applicable','unverified','partial','verified','rejected')),
 display_track TEXT, display_name_en TEXT, display_name_zh TEXT,
 domain TEXT NOT NULL, sub_domain TEXT, scenario_description TEXT,
 max_latency_ns INTEGER, min_latency_ns INTEGER, physical_latency_limit_ns INTEGER,
 classical_communication_feasible INTEGER CHECK(classical_communication_feasible IN (0,1)),
 quantum_mechanism TEXT, proof_type TEXT CHECK(proof_type IN ('strict','heuristic')),
 quantum_advantage_ratio REAL, qubits_required INTEGER, entanglement_pairs_required INTEGER,
 fault_tolerance_needed INTEGER CHECK(fault_tolerance_needed IN (0,1)),
 adversary_model TEXT, security_guarantee TEXT, quantum_channel TEXT,
 distance_km_max REAL, key_rate_bps_max REAL,
 cost_usd_min REAL, cost_usd_max REAL, deployment_years_min REAL, deployment_years_max REAL,
 metrics_provenance TEXT CHECK(metrics_provenance IS NULL OR json_valid(metrics_provenance)),
 field_provenance TEXT CHECK(field_provenance IS NULL OR json_valid(field_provenance)),
 scenario_description_source TEXT CHECK(scenario_description_source IN ('from_document','ai_inference')),
 deployment_stage TEXT CHECK(deployment_stage IN ('experimental','pilot','production')),
 problem_definition_complete INTEGER CHECK(problem_definition_complete IN (0,1)),
 CHECK(cost_usd_min IS NULL OR cost_usd_max IS NULL OR cost_usd_min <= cost_usd_max),
 CHECK(deployment_years_min IS NULL OR deployment_years_max IS NULL OR deployment_years_min <= deployment_years_max),
 CHECK(min_latency_ns IS NULL OR max_latency_ns IS NULL OR min_latency_ns <= max_latency_ns)
);
CREATE INDEX idx_cases_domain ON cases(domain);
CREATE INDEX idx_cases_max_latency ON cases(max_latency_ns);
CREATE INDEX idx_cases_cost_max ON cases(cost_usd_max);
CREATE INDEX idx_cases_deployment_max ON cases(deployment_years_max);
CREATE TABLE case_problem_definitions (
 case_id TEXT NOT NULL REFERENCES cases(case_id),
 field TEXT NOT NULL CHECK(field IN ('real_world_problem','parties_and_roles','inputs_and_outputs','constraints','existing_practice','quantum_mechanism_role','success_criteria','deployment_boundary')),
 value_text TEXT, quote TEXT, location TEXT,
 evidence_level TEXT CHECK(evidence_level IN ('primary','secondary')),
 confidence TEXT CHECK(confidence IN ('high','medium','low')),
 source_id TEXT REFERENCES seen_sources(source_id), search_log_id INTEGER REFERENCES search_log(log_id), reason TEXT,
 PRIMARY KEY(case_id,field),
 CHECK((value_text IS NOT NULL AND COALESCE(length(trim(quote)),0)>0 AND COALESCE(length(trim(location)),0)>0 AND source_id IS NOT NULL AND search_log_id IS NOT NULL AND evidence_level IS NOT NULL AND confidence IS NOT NULL) OR (value_text IS NULL AND reason IS NOT NULL AND evidence_level IS NULL AND confidence IS NULL AND quote IS NULL AND location IS NULL AND source_id IS NULL AND search_log_id IS NULL))
);
CREATE INDEX idx_problem_defs_field ON case_problem_definitions(field);
CREATE TABLE case_tracks (
 case_id TEXT NOT NULL REFERENCES cases(case_id),
 track_id TEXT NOT NULL CHECK(track_id IN ('nonlocal-coordination','quantum-security')),
 passed_admission INTEGER NOT NULL CHECK(passed_admission IN (0,1)),
 score_total REAL CHECK(score_total IS NULL OR score_total >= 0), -- max_score is track-configured; do not hard-code a global upper bound
 score_normalized REAL CHECK(score_normalized BETWEEN 0 AND 25),
 min_total_score INTEGER, display_order INTEGER CHECK(display_order IS NULL OR display_order IN (0,1)),
 PRIMARY KEY(case_id,track_id)
);
CREATE INDEX idx_case_tracks_track ON case_tracks(track_id);
CREATE INDEX idx_case_tracks_score ON case_tracks(track_id,score_normalized);
CREATE TABLE case_evaluations (
 case_id TEXT NOT NULL REFERENCES cases(case_id), track_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('admission','score')), key TEXT NOT NULL,
 value_text TEXT CHECK(value_text IN ('true','false','insufficient_evidence')),
 value_num INTEGER CHECK(value_num IN (1,3,5)),
 confidence TEXT CHECK(confidence IN ('high','medium','low')),
 evidence_level TEXT CHECK(evidence_level IN ('primary','secondary','ai_inference')),
 quote TEXT, location TEXT, reason TEXT,
 _source TEXT NOT NULL CHECK(_source = 'from_document'),
 source_id TEXT REFERENCES seen_sources(source_id), search_log_id INTEGER REFERENCES search_log(log_id),
 single_source INTEGER CHECK(single_source IN (0,1)),
 evidence_json TEXT CHECK(evidence_json IS NULL OR json_valid(evidence_json)),
 PRIMARY KEY(case_id,track_id,kind,key),
 CHECK(evidence_level IS NULL OR evidence_level != 'ai_inference'),
 CHECK((kind='admission' AND value_text IS NOT NULL AND value_num IS NULL)
    OR (kind='score' AND value_text IS NULL)),
 CHECK((kind='admission' AND value_text='insufficient_evidence') OR
       (kind='score' AND value_num IS NULL) OR
       (COALESCE(length(trim(quote)),0)>0 AND COALESCE(length(trim(location)),0)>0 AND source_id IS NOT NULL AND search_log_id IS NOT NULL AND _source IS NOT NULL AND evidence_level IS NOT NULL AND confidence IS NOT NULL))
);
CREATE INDEX idx_evals_key ON case_evaluations(kind,key);
CREATE TABLE case_sources (
 case_id TEXT NOT NULL REFERENCES cases(case_id),
 source_id TEXT NOT NULL REFERENCES seen_sources(source_id),
 role TEXT NOT NULL CHECK(role IN ('primary','supporting')),
 supports_criteria TEXT CHECK(supports_criteria IS NULL OR json_valid(supports_criteria)),
 evidence_level TEXT CHECK(evidence_level IN ('primary','secondary')),
 retrieved_at TEXT,
 PRIMARY KEY(case_id, source_id)
);
CREATE INDEX idx_case_sources_source ON case_sources(source_id);
CREATE TABLE excluded_cases (
 excluded_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT,
 source TEXT,
 reason TEXT CHECK(reason IN ('excluded_by_policy','failed_admission','classical_infrastructure','not_an_application_case','insufficient_evidence','not_modelable_as_nonlocal_game','classical_workaround_exists','problem_definition_incomplete','not_a_real_world_problem')),
 matched_rule TEXT, matched_field TEXT, matched_text TEXT, detail TEXT, timestamp TEXT,
 run_id TEXT, batch_id TEXT
);
