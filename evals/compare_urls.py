# %%%
from __future__ import annotations
import click
import os

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlsplit

import pandas as pd
import re

DEFAULT_PORTS = {"http": 80, "https": 443}
URL_REGEX = re.compile(
    # Capture Markdown links or bare URLs; allow embedded quotes (e.g., unencoded filterJson fragments)
    r"(?:\[[^\]]*\]\((https?://[^)\s]+)\))|(https?://[^\s<>]+)",
    re.IGNORECASE,
)
SPECIAL_QUERY_KEYS = {"session_id", "comparisonId"}


def _normalize_url(url: str) -> Dict[str, Any]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    default_port = DEFAULT_PORTS.get(scheme)
    port = parts.port if parts.port and parts.port != default_port else None
    path = unquote(parts.path or "/")
    query_pairs = [(unquote(k), unquote(v))
                   for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    fragment = unquote(parts.fragment)
    return {
        "scheme": scheme,
        "host": host,
        "port": port,
        "path": path,
        "query_pairs": query_pairs,
        "fragment": fragment,
    }


def _multimap(pairs: Iterable[Tuple[str, str]]) -> Dict[str, List[str]]:
    m: Dict[str, List[str]] = {}
    for k, v in pairs:
        m.setdefault(k, []).append(v)
    return m


def _normalize_value(
    val: Any,
    treat_csv_as_set: bool,
    double_unquote: bool,
    alt_split: bool,
) -> Any:
    if isinstance(val, list):
        return sorted(val)
    if isinstance(val, str):
        v = val
        if double_unquote:
            v = unquote(v)
        if treat_csv_as_set:
            separators = [","] + ([";", "\n"] if alt_split else [])
            sep_used = None
            for sep in separators:
                if sep in v:
                    sep_used = sep
                    break
            if sep_used:
                return sorted(part.strip() for part in v.split(sep_used) if part.strip() != "")
        return v
    return val


def _try_json(val: str) -> Optional[Any]:
    try:
        return json.loads(val)
    except Exception:
        return None


@dataclass
class Node:
    name: str
    expected: Any
    actual: Any
    match: bool
    children: List["Node"] = field(default_factory=list)


def score_urls(
    expected: str,
    actual: str,
    *,
    treat_csv_lists_as_sets: bool = True,
    treat_semicolon_newline_lists_as_sets: bool = True,
    double_unquote_values: bool = True,
    include_fragment: bool = True,
) -> Tuple[float, pd.DataFrame]:
    """
    Hierarchical URL scoring. Each node splits its weight equally among children; only matching
    leaves contribute to the total (which sums to 1.0). Returns (total_score, dataframe).
    The dataframe includes node_id, component, expected, actual, match, weight, and score.
    """
    exp = _normalize_url(expected)
    act = _normalize_url(actual)

    def normalize_val(v):
        return _normalize_value(
            v,
            treat_csv_lists_as_sets,
            double_unquote_values,
            treat_semicolon_newline_lists_as_sets,
        )

    def build_json_nodes(prefix: str, ev: Any, av: Any) -> List[Node]:
        if isinstance(ev, dict) and isinstance(av, dict):
            keys = sorted(set(ev.keys()) | set(av.keys()))
            nodes = []
            for k in keys:
                child_prefix = f"{prefix}.{k}" if prefix else k
                ev_child = ev.get(k)
                av_child = av.get(k)
                match = ev_child == av_child
                children = build_json_nodes(child_prefix, ev_child, av_child)
                nodes.append(Node(child_prefix, ev_child,
                             av_child, match, children))
            return nodes
        if isinstance(ev, list) and isinstance(av, list):
            max_len = max(len(ev), len(av))
            nodes = []
            for i in range(max_len):
                ev_item = ev[i] if i < len(ev) else None
                av_item = av[i] if i < len(av) else None
                child_prefix = f"{prefix}[{i}]"
                match = ev_item == av_item
                children = build_json_nodes(child_prefix, ev_item, av_item)
                nodes.append(Node(child_prefix, ev_item,
                             av_item, match, children))
            return nodes
        return []

    def build_tree() -> List[Node]:
        nodes: List[Node] = []

        core_children = [
            Node("scheme", exp["scheme"], act["scheme"],
                 exp["scheme"] == act["scheme"]),
            Node("host", exp["host"], act["host"], exp["host"] == act["host"]),
            Node("port", exp["port"], act["port"], exp["port"] == act["port"]),
        ]
        core_match = all(child.match for child in core_children)
        nodes.append(Node("core", None, None, core_match, core_children))

        path_children: List[Node] = []
        exp_segments = [seg for seg in exp["path"].strip(
            "/").split("/") if seg] if exp["path"] != "/" else []
        act_segments = [seg for seg in act["path"].strip(
            "/").split("/") if seg] if act["path"] != "/" else []
        max_len = max(len(exp_segments), len(act_segments))
        for idx in range(max_len):
            ev = exp_segments[idx] if idx < len(exp_segments) else None
            av = act_segments[idx] if idx < len(act_segments) else None
            path_children.append(Node(f"path[{idx}]", ev, av, ev == av))
        nodes.append(Node(
            "path", exp["path"], act["path"], exp["path"] == act["path"], path_children))

        exp_q = _multimap(exp["query_pairs"])
        act_q = _multimap(act["query_pairs"])
        query_children: List[Node] = []
        query_keys = sorted(set(exp_q.keys()) | set(act_q.keys()))

        separators = [
            ",", ";", "\n"] if treat_semicolon_newline_lists_as_sets else [","]

        def explode_list(vals: Optional[List[str]]) -> List[str]:
            if not vals:
                return []
            exploded: List[str] = []
            for v in vals:
                if isinstance(v, str) and treat_csv_lists_as_sets:
                    v_work = unquote(v) if double_unquote_values else v
                    for sep in separators:
                        if sep in v_work:
                            exploded.extend(
                                part.strip() for part in v_work.split(sep) if part.strip())
                            break
                    else:
                        exploded.append(v_work)
                else:
                    exploded.append(v)
            return exploded

        for key in query_keys:
            ev_list = exp_q.get(key)
            av_list = act_q.get(key)
            key_match = normalize_val(ev_list) == normalize_val(av_list)
            value_children: List[Node] = []
            if not key_match and (ev_list is not None or av_list is not None):
                ev_vals = explode_list(ev_list)
                av_vals = explode_list(av_list)
                exp_counter = Counter(ev_vals)
                act_counter = Counter(av_vals)
                all_vals = sorted(set(exp_counter.keys()) |
                                  set(act_counter.keys()))
                idx = 0
                for val in all_vals:
                    matched = min(exp_counter.get(val, 0),
                                  act_counter.get(val, 0))
                    for _ in range(matched):
                        json_children: List[Node] = []
                        ev_json = _try_json(val)
                        av_json = _try_json(val)
                        if isinstance(ev_json, (dict, list)) and isinstance(av_json, (dict, list)):
                            json_children = build_json_nodes(
                                f"query[{key}][{idx}]", ev_json, av_json)
                        value_children.append(
                            Node(f"query[{key}][{idx}]", val, val, True, json_children))
                        idx += 1
                    exp_extra = exp_counter.get(val, 0) - matched
                    act_extra = act_counter.get(val, 0) - matched
                    for _ in range(exp_extra):
                        value_children.append(
                            Node(f"query[{key}][{idx}]", val, None, False, []))
                        idx += 1
                    for _ in range(act_extra):
                        value_children.append(
                            Node(f"query[{key}][{idx}]", None, val, False, []))
                        idx += 1
            query_children.append(
                Node(f"query[{key}]", ev_list, av_list, key_match, value_children))
        nodes.append(Node("query", exp_q, act_q, normalize_val(
            exp_q) == normalize_val(act_q), query_children))

        if include_fragment:
            frag_children: List[Node] = []
            frag_match = exp["fragment"] == act["fragment"]

            def split_frag(frag: str) -> Tuple[Optional[str], Optional[str]]:
                if not frag:
                    return None, None
                return frag.split("=", 1) if "=" in frag else (None, frag)

            exp_fk, exp_fv = split_frag(exp["fragment"])
            act_fk, act_fv = split_frag(act["fragment"])
            if exp_fk is not None or act_fk is not None:
                frag_children.append(
                    Node("fragment.key", exp_fk, act_fk, exp_fk == act_fk))
            if exp_fv is not None or act_fv is not None:
                fv_match = exp_fv == act_fv
                fv_children: List[Node] = []
                if exp_fv and act_fv:
                    exp_json = _try_json(exp_fv)
                    act_json = _try_json(act_fv)
                    if isinstance(exp_json, (dict, list)) and isinstance(act_json, (dict, list)):
                        fv_children = build_json_nodes(
                            "fragment.value", exp_json, act_json)
                frag_children.append(
                    Node("fragment.value", exp_fv, act_fv, fv_match, fv_children))
            if frag_children or exp["fragment"] or act["fragment"]:
                nodes.append(
                    Node("fragment", exp["fragment"], act["fragment"], frag_match, frag_children))

        return nodes

    tree = build_tree()
    rows: List[Dict[str, Any]] = []

    NON_SCORING_COMPONENTS = {"core", "scheme", "host", "port"}

    def assign_scores(node: Node, weight: float, label: str) -> float:
        """
        Only leaf matches contribute to the total. Internal nodes still get rows for visibility.
        node_id uses dotted numeric paths (e.g., 1.2.1).
        """
        if node.name in NON_SCORING_COMPONENTS:
            weight = 0.0

        if node.children:
            child_weight = weight / len(node.children)
            child_contrib = 0.0
            for idx, child in enumerate(node.children, start=1):
                child_label = f"{label}.{idx}"
                child_contrib += assign_scores(child,
                                               child_weight, child_label)
            rows.append(
                {
                    "node_id": label,
                    "component": node.name,
                    "expected": node.expected,
                    "actual": node.actual,
                    "match": node.match,
                    "weight": weight,
                    "counts": False,
                    "score": 0.0,  # internal nodes do not add to total; only leaves count
                }
            )
            return child_contrib
        else:
            contrib = weight if node.match else 0.0
            counts = weight > 0.0
            rows.append(
                {
                    "node_id": label,
                    "component": node.name,
                    "expected": node.expected,
                    "actual": node.actual,
                    "match": node.match,
                    "weight": weight,
                    "counts": counts,
                    "score": contrib,
                }
            )
            return contrib

    if not tree:
        return 0.0, pd.DataFrame()

    scoring_nodes = [n for n in tree if n.name not in NON_SCORING_COMPONENTS]
    if not scoring_nodes:
        return 0.0, pd.DataFrame()

    top_weight = 1.0 / len(scoring_nodes)
    total_score = 0.0
    for idx, n in enumerate(tree, start=1):
        weight = top_weight if n.name not in NON_SCORING_COMPONENTS else 0.0
        total_score += assign_scores(n, weight, str(idx))

    return total_score, pd.DataFrame(rows)


def _strip_unbalanced_trailing_parens(url: str) -> str:
    """Remove closing parens that wrap Markdown links while keeping balanced ones inside URLs."""

    if not url:
        return url

    opens = url.count("(")
    closes = url.count(")")
    while url.endswith(")") and closes > opens:
        url = url[:-1]
        closes -= 1
    return url.rstrip(".,;:")


def _compact_filter_json_blocks(text: str) -> str:
    """
    Remove whitespace/newlines inside #filterJson={...} fragments so URLs are contiguous.
    Handles nested braces and leaves unmatched fragments untouched.
    """
    token = "#filterJson={"
    pieces: List[str] = []
    idx = 0

    while True:
        start = text.find(token, idx)
        if start == -1:
            pieces.append(text[idx:])
            break

        pieces.append(text[idx:start])
        j = start + len(token)
        depth = 1
        while j < len(text) and depth > 0:
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1

        fragment = text[start:j]
        compact = "".join(fragment.split())
        pieces.append(compact)
        idx = j

    return "".join(pieces)


def extract_urls(text: str) -> List[str]:
    """
    Extract all URLs from the given text, including Markdown links.
    """
    text = _compact_filter_json_blocks(text or "")

    urls: List[str] = []
    seen = set()

    for md_url, bare_url in URL_REGEX.findall(text):
        url = md_url or bare_url
        cleaned = _strip_unbalanced_trailing_parens(url)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)

    return urls


def _extract_special_query_ids(url: str) -> Dict[str, List[str]]:
    """
    Pull out values for session_id/comparisonId from a single URL's query string.
    """
    if not url:
        return {}
    try:
        parts = urlsplit(url)
    except Exception:
        return {}
    found: Dict[str, List[str]] = {}
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k in SPECIAL_QUERY_KEYS:
            found.setdefault(k, []).append(v)
    return found


def collect_special_query_ids(urls: Iterable[str]) -> Dict[str, List[str]]:
    """
    Aggregate special query ids across a collection of URLs, deduplicating values.
    """
    combined: Dict[str, List[str]] = {}
    for url in urls:
        for k, vals in _extract_special_query_ids(url).items():
            for v in vals:
                if v not in combined.setdefault(k, []):
                    combined[k].append(v)
    return combined


def handle_special_query_ids(ids: Dict[str, List[str]], *, question_id: Optional[Any] = None) -> None:
    """
    Placeholder hook to act on session/comparison ids. Currently a no-op.
    """
    return


@click.command()
@click.option('--input-csv', required=True, help='Path to input CSV file containing questions and expected answers.')
@click.option('--answers-dir', required=True, help='Directory containing LLM output files.')
@click.option('--output-dir', default='evaluation_results', help='Path to save evaluation results.')
@click.option('--answer-column', default='Claude Clickhouse MCP Answer', help='Name of the column in input-csv that contains the expected human answer.')
def main(input_csv: str, answers_dir: str, output_dir: str, answer_column: str):
    sep = '\t' if str(input_csv).endswith('.tsv') else ','
    data = pd.read_csv(input_csv, sep=sep)

    assert answer_column in data.columns, f"Warning: Expected answer column '{answer_column}' not found in CSV. Available: {data.columns}"

    os.makedirs(output_dir, exist_ok=True)
    scores = dict()
    special_flags: Dict[int, str] = dict()
    # Iterate over each row in the input CSV and evaluate the LLM output
    for idx, row in data.iterrows():
        print(f'Processing Q{idx+1}...')
        qidx = idx + 1

        if 'Question ID' in row:
            qid = row['Question ID']
        else:
            qid = qidx

        answer_file_path = os.path.join(answers_dir, f'{qid}.md')

        if not os.path.isfile(answer_file_path):
            # Fallback to just index if ID didn't work
            answer_file_path = os.path.join(answers_dir, f'{qidx}.md')
            if not os.path.isfile(answer_file_path):
                continue

        with open(answer_file_path, 'r') as file:
            llm_output = file.read()

        expected_val = row[answer_column]

        if pd.isnull(expected_val):
            print(f'Q{qidx} No expected value, skipping.')
            continue

        answer_urls = extract_urls(llm_output)
        expected_urls = extract_urls(str(expected_val))

        if len(expected_urls) == 0:
            print(f'Q{qidx} No expected URLs found, skipping.')
            continue

        answer_urls = [ans for ans in answer_urls if 'cbioportal.org' in ans]

        special_ids = collect_special_query_ids(expected_urls + answer_urls)
        handle_special_query_ids(special_ids, question_id=qidx)
        if special_ids:
            special_flags[qidx] = "; ".join(
                f"{k}={','.join(vals) if vals else ''}".rstrip("=")
                for k, vals in special_ids.items()
            )
            print(f'Q{qidx} contains special query ids: {special_flags[qidx]}')
        else:
            special_flags[qidx] = ""

        max_score = 0.0
        max_df = pd.DataFrame()

        if len(expected_urls) > 0:
            for exp_url in expected_urls:
                for ans_url in answer_urls:
                    print(f'E: {exp_url}, A: {ans_url}')
                    score, df = score_urls(exp_url, ans_url)
                    max_score = max(max_score, score)
                    if score == max_score:
                        max_df = df

        print(f'Q{qidx} Max URL Score: {max_score:.4f}')

        scores[qidx] = max_score
        max_df.to_csv(os.path.join(
            output_dir, f'url_result_q{qidx}.tsv'), index=False, sep='\t')

    score_series = pd.Series(scores)
    special_series = pd.Series(special_flags)
    summary_df = pd.DataFrame(
        {
            'score': score_series,
            'special_query_ids': special_series,
        }
    )
    average_score = summary_df['score'].mean()
    print(f"\n\nAverage URL Score across all questions: {average_score:.4f}")
    summary_df.to_csv(os.path.join(output_dir, 'url_scores_summary.tsv'),
                      index_label='question_id', sep='\t')


# %%
