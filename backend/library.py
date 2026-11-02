"""Decides what a library save is allowed to do. Pure Python with no database, so every rule can be unit tested.

The dashboard sends one request holding every change: files to save (new or updated), files to delete, and the
same for the collection. Each existing file carries the revision the dashboard last saw. If someone else changed
it since, the whole request is refused with a conflict and nothing is written.
"""
from .validators import MAX_SPECS, validate_collection, validate_spec


class ApplyError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


def _revision_conflict(kind: str, name: str, current: dict | None, expected: int | None, creating: bool):
    """Returns a conflict entry when the file is not in the state the dashboard thinks it is, otherwise None."""
    if current is None:
        # Saving a file the dashboard thought existed means someone deleted it. Deleting a missing file is fine.
        return {"kind": kind, "name": name, "reason": "deleted"} if creating and expected is not None else None
    if creating and expected is None:
        return {"kind": kind, "name": name, "reason": "exists"}
    if expected is not None and expected != current["revision"]:
        return {"kind": kind, "name": name, "reason": "changed"}
    return None


def plan_apply(existing_specs: dict, existing_col: dict | None, body: dict) -> dict:
    """existing_specs maps name to {"revision", "text"}. existing_col is {"revision", "name", "text"} or None.

    Returns {"upsert", "delete", "collection", "delete_collection", "summary"} or raises ApplyError.
    """
    specs_in = body.get("specs") or []
    deletes = body.get("delete_specs") or []
    col_in = body.get("collection")
    col_del = body.get("delete_collection")

    if col_in and col_del:
        raise ApplyError(422, "The collection cannot be saved and deleted in the same request")
    delete_names = [d["name"] for d in deletes]
    if len(set(delete_names)) != len(delete_names):
        raise ApplyError(422, "A file is listed twice for deletion")

    problems: dict[str, list[str]] = {}
    existing_by_fold = {n.casefold(): n for n in existing_specs}
    seen: dict[str, str] = {}
    upsert = []

    for f in specs_in:
        name = f["name"]
        fold = name.casefold()
        if fold in seen:
            problems.setdefault(name, []).append(
                "Listed twice in this request" if seen[fold] == name else f'Differs only by letter case from "{seen[fold]}"')
            continue
        seen[fold] = name
        result = validate_spec(name, f["text"])
        if result["errors"]:
            problems[name] = result["errors"]
            continue
        if name in delete_names:
            problems[name] = ["Cannot be saved and deleted in the same request"]
            continue
        other = existing_by_fold.get(fold)
        if other and other != name and other not in delete_names:
            problems[name] = [f'Differs only by letter case from the saved file "{other}"']
            continue
        upsert.append({"name": name, "text": f["text"], "revision": f.get("revision"), "tests": len(result["tests"])})

    collection = None
    if col_in:
        result = validate_collection(col_in["name"], col_in["text"])
        if result["errors"]:
            problems[col_in["name"]] = result["errors"]
        else:
            collection = {"name": col_in["name"], "text": col_in["text"], "revision": col_in.get("revision"),
                          "requests": len(result["requests"])}
    if problems:
        raise ApplyError(422, {"files": problems})

    conflicts = []
    for item in upsert:
        c = _revision_conflict("spec", item["name"], existing_specs.get(item["name"]), item["revision"], True)
        if c:
            conflicts.append(c)
    for d in deletes:
        c = _revision_conflict("spec", d["name"], existing_specs.get(d["name"]), d.get("revision"), False)
        if c:
            conflicts.append(c)
    if collection:
        c = _revision_conflict("collection", collection["name"], existing_col, collection["revision"], True)
        if c:
            conflicts.append(c)
    if col_del:
        c = _revision_conflict("collection", existing_col["name"] if existing_col else "", existing_col, col_del.get("revision"), False)
        if c:
            conflicts.append(c)
    if conflicts:
        raise ApplyError(409, {"conflicts": conflicts})

    final = (set(existing_specs) - set(delete_names)) | {u["name"] for u in upsert}
    if len(final) > MAX_SPECS:
        raise ApplyError(422, f"A library holds at most {MAX_SPECS} spec files")

    # Nothing to write for files that are already exactly as sent.
    changed = [u for u in upsert if not (u["name"] in existing_specs and existing_specs[u["name"]]["text"] == u["text"])]
    for u in changed:
        u["exists"] = u["name"] in existing_specs
    removed = [n for n in delete_names if n in existing_specs]

    if collection and existing_col and existing_col["name"] == collection["name"] and existing_col["text"] == collection["text"]:
        collection = None
    elif collection:
        collection["exists"] = existing_col is not None

    delete_collection = bool(col_del and existing_col)
    return {
        "upsert": changed,
        "delete": removed,
        "collection": collection,
        "delete_collection": delete_collection,
        "summary": {
            "saved_specs": len(changed),
            "removed_specs": len(removed),
            "saved_collection": bool(collection),
            "removed_collection": delete_collection,
        },
    }