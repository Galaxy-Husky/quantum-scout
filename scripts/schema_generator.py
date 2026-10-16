#!/usr/bin/env python3
"""Generate SearchOS tables and prompt skills from the existing domain contracts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import yaml
from searchos_project import ProjectLayout, save

SKILL_ROOT = Path(__file__).resolve().parents[1]
TRACK_SKILLS = {"nonlocal-coordination": "quantum-nlc-admission",
                "quantum-security": "quantum-security-admission"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def prompt_rule(rule):
    """Explain an otherwise label-only feasibility rule without changing its condition."""
    if rule.get("require_fault_tolerance") is False and not rule.get("description"):
        return {**rule, "description": (
            "Evaluate whether this protocol can be implemented without fault-tolerant quantum computing. "
            "Commercial readiness, network range and deployment years are not requirements of this criterion. "
            "Laboratory status alone establishes neither true nor false; require body evidence about "
            "the actual hardware and computation needed. Missing evidence remains insufficient_evidence.")}
    return rule


def domain_config(config_dir=SKILL_ROOT / "config"):
    config_dir = Path(config_dir)
    tracks = yaml.safe_load((config_dir / "tracks.yaml").read_text())
    ddl = (config_dir / "schema.sql").read_text()
    table = ddl.split("CREATE TABLE case_problem_definitions (", 1)[1].split("CREATE INDEX", 1)[0]
    match = re.search(r"CHECK\(field IN \((.*?)\)\)", table)
    fields = re.findall(r"'([^']+)'", match.group(1)) if match else []
    if len(fields) != 8 or len(set(fields)) != 8:
        raise ValueError("schema.sql must define the eight problem fields")
    if set(tracks["tracks"]) != set(TRACK_SKILLS):
        raise ValueError("Track strategy mapping needs an explicit update")
    return {"fields": fields, **tracks,
            "exclusions": yaml.safe_load((config_dir / "exclusions.yaml").read_text()),
            "scope": yaml.safe_load((config_dir / "scope.yaml").read_text())}


def generate(case_ids, config=None):
    config = config or domain_config()
    if len(case_ids) != len(set(case_ids)) or any(not re.fullmatch(r"[A-Z]{3,4}-\d{4}", c) for c in case_ids):
        raise ValueError("case_ids must be unique domain IDs, e.g. TEL-0001")
    field_rules = dict(re.findall(r"^\| (\w+) \| ([^|]+) \|",
        (SKILL_ROOT / "references/evidence.md").read_text(), re.MULTILINE))
    if any(not field_rules.get(f, "").strip() for f in config["fields"]):
        raise ValueError("evidence.md must describe every problem field")
    tables = [{"table_id": "problem_definition", "table_label": "案例问题定义",
               "entities": case_ids, "attributes": config["fields"], "primary_key": [],
               "column_desc": {f: {"type": "str", "desc": field_rules[f] + ": sourced value; missing reason is not evidence"}
                               for f in config["fields"]}}]
    for track, rules in config["tracks"].items():
        for kind, key in (("admission", "admission_criteria"), ("scoring", "scoring_dimensions")):
            columns = rules[key]
            allowed = ["true", "false", "insufficient_evidence"] if kind == "admission" else ["1", "3", "5"]
            tables.append({"table_id": track + "_" + kind,
                           "table_label": rules["display_name_zh"] + " " + kind,
                           "entities": case_ids, "attributes": list(columns), "primary_key": [],
                           "column_desc": {name: {"type": "str", "desc": json.dumps(prompt_rule(rule), ensure_ascii=False),
                                                   "check": {"enum": allowed}}
                                           for name, rule in columns.items()}})
    return {"version": 1, "config_sha256": digest(config), "coverage_role": "scheduling_only",
            "semantic_verifier": "unavailable", "tables": tables}


def write_strategy_skills(directory, config):
    """Generated prompt documents, not executable strategies."""
    common = ("只使用本次已打开正文。先建立八字段问题定义；缺证保留 insufficient_evidence/null。\n"
              "引文必须先经 quantum_grounding，再独立核查语义、位置、场景和安全边界。\n"
              "单一来源 confidence 最高 medium；C3/S2 优先两个独立来源。\n"
              "禁止 HFT、defense、启发式优势、容错计算前提；Bell 不是超光速通信。\n"
              "Coverage Map 只调度，不能据此宣布证据充分或全局耗尽。\n")
    payloads = {}
    for track, name in TRACK_SKILLS.items():
        payloads[name] = (f"评估 {track} 的四项准入", common +
                         "输出 JSON：case_id、track_id、criteria（每项 true/false/insufficient_evidence）、"
                         "逐项 evidence_refs 和 reason；false 也需证据。\n"
                         "准入与评分独立；仅全部 true 才 passed_admission=true。\n",
                         {"track_id": track, "criteria": config["tracks"][track]["admission_criteria"],
                          "mechanisms": config["tracks"][track]["mechanisms"]})
    payloads["quantum-scoring"] = ("按量子 Track 锚点评分", common +
        "仅准入通过后评分。输出 JSON：case_id、track_id、scores（每维 1/3/5/null）、"
        "逐维 evidence_refs、reason、valid_dimension_count、score_total、score_normalized。\n"
        "不足最少有效维数则 score_normalized=null，不能回改准入；禁止估算部署年限或成本。\n",
        {"scoring_rules": config["scoring_rules"], "tracks": {
            t: {"dimensions": r["scoring_dimensions"], "min_total_score": r["min_total_score"]}
            for t, r in config["tracks"].items()}})
    for name, (description, instructions, rules) in payloads.items():
        folder = Path(directory) / "strategy" / name
        folder.mkdir(parents=True, exist_ok=True)
        front = yaml.safe_dump({"name": name, "description": description,
                               "category": "strategy", "status": "seed",
                               "config_sha256": digest(config),
                               "generated_at": datetime.now(timezone.utc).isoformat()}, allow_unicode=True)
        body = f"---\n{front}---\n\n{instructions}\n配置哈希：{digest(config)}\n\n```yaml\n"
        body += yaml.safe_dump(rules, allow_unicode=True, sort_keys=False) + "```\n"
        (folder / "skill.md").write_text(body, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--config-dir", type=Path, default=SKILL_ROOT / "config")
    parser.add_argument("--skills-dir", type=Path)
    args = parser.parse_args()
    config = domain_config(args.config_dir)
    save(args.output or ProjectLayout(args.project_root).schema, generate(args.case_id, config))
    if args.skills_dir:
        write_strategy_skills(args.skills_dir, config)


if __name__ == "__main__":
    main()
