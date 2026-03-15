"""ConstructClaw -- Safety & Compliance domain module.

Incidents, toolbox talks, safety certifications, OSHA reporting.
12 actions exported via ACTIONS dict.
"""
import os
import sys
import uuid
from datetime import date as _date, datetime
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.naming import get_next_name, register_prefix
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row

SKILL = "constructclaw"

register_prefix("constructclaw_incident", "CCINC-")

VALID_INCIDENT_TYPES = (
    "near_miss", "first_aid", "recordable", "lost_time",
    "fatality", "property_damage", "environmental", "other",
)
VALID_SEVERITIES = ("minor", "moderate", "serious", "critical", "fatal")
VALID_INCIDENT_STATUSES = ("open", "investigating", "corrective_action", "closed")
VALID_CERT_STATUSES = ("active", "expiring_soon", "expired", "revoked")


# ---------------------------------------------------------------------------
# add-incident
# ---------------------------------------------------------------------------
def add_incident(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "description", None):
        err("--description is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    incident_type = getattr(args, "incident_type", None) or "near_miss"
    if incident_type not in VALID_INCIDENT_TYPES:
        err(f"Invalid incident-type: {incident_type}")

    severity = getattr(args, "severity", None) or "minor"
    if severity not in VALID_SEVERITIES:
        err(f"Invalid severity: {severity}")

    inc_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_incident", company_id=args.company_id)

    osha_recordable = 1 if incident_type in ("recordable", "lost_time", "fatality") else 0

    sql, _ = insert_row("constructclaw_incident", {"id": P(), "naming_series": P(), "incident_number": P(), "job_id": P(), "incident_date": P(), "incident_time": P(), "incident_type": P(), "severity": P(), "location": P(), "description": P(), "injured_party": P(), "witnesses": P(), "root_cause": P(), "corrective_action": P(), "osha_recordable": P(), "days_lost": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            inc_id, ns, ns, job_id,
            getattr(args, "incident_date", None) or _date.today().isoformat(),
            getattr(args, "incident_time", None),
            incident_type, severity,
            getattr(args, "location", None),
            args.description,
            getattr(args, "injured_party", None),
            getattr(args, "witnesses", None),
            getattr(args, "root_cause", None),
            getattr(args, "corrective_action", None),
            osha_recordable,
            int(getattr(args, "days_lost", None) or 0),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-incident", "constructclaw_incident", inc_id,
          new_values={"naming_series": ns, "incident_type": incident_type})
    conn.commit()
    ok({"incident_id": inc_id, "naming_series": ns,
        "incident_type": incident_type, "severity": severity,
        "osha_recordable": osha_recordable, "incident_status": "open"})


# ---------------------------------------------------------------------------
# update-incident
# ---------------------------------------------------------------------------
def update_incident(conn, args):
    inc_id = getattr(args, "incident_id", None)
    if not inc_id:
        err("--incident-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_incident")).select(Table("constructclaw_incident").star).where(Field("id") == P()).get_sql(), (inc_id,)).fetchone()
    if not row:
        err(f"Incident {inc_id} not found")

    updates, params, changed = [], [], []
    for field, attr in [
        ("incident_date", "incident_date"), ("incident_time", "incident_time"),
        ("location", "location"), ("description", "description"),
        ("injured_party", "injured_party"), ("witnesses", "witnesses"),
        ("root_cause", "root_cause"), ("corrective_action", "corrective_action"),
        ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(val)
            changed.append(field)

    it = getattr(args, "incident_type", None)
    if it is not None:
        if it not in VALID_INCIDENT_TYPES:
            err(f"Invalid incident-type: {it}")
        updates.append("incident_type = ?")
        params.append(it)
        changed.append("incident_type")

    sev = getattr(args, "severity", None)
    if sev is not None:
        if sev not in VALID_SEVERITIES:
            err(f"Invalid severity: {sev}")
        updates.append("severity = ?")
        params.append(sev)
        changed.append("severity")

    dl = getattr(args, "days_lost", None)
    if dl is not None:
        updates.append("days_lost = ?")
        params.append(int(dl))
        changed.append("days_lost")

    osha = getattr(args, "osha_recordable", None)
    if osha is not None:
        updates.append("osha_recordable = ?")
        params.append(int(osha))
        changed.append("osha_recordable")

    if not changed:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(inc_id)
    conn.execute(
        f"UPDATE constructclaw_incident SET {', '.join(updates)} WHERE id = ?", params
    )
    audit(conn, SKILL, "construction-update-incident", "constructclaw_incident", inc_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"incident_id": inc_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# get-incident
# ---------------------------------------------------------------------------
def get_incident(conn, args):
    inc_id = getattr(args, "incident_id", None)
    if not inc_id:
        err("--incident-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_incident")).select(Table("constructclaw_incident").star).where(Field("id") == P()).get_sql(), (inc_id,)).fetchone()
    if not row:
        err(f"Incident {inc_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# list-incidents
# ---------------------------------------------------------------------------
def list_incidents(conn, args):
    conditions, params = [], []
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    it = getattr(args, "incident_type", None)
    if it:
        conditions.append("incident_type = ?")
        params.append(it)
    ist = getattr(args, "incident_status", None)
    if ist:
        conditions.append("incident_status = ?")
        params.append(ist)
    search = getattr(args, "search", None)
    if search:
        conditions.append("(description LIKE ? OR injured_party LIKE ? OR location LIKE ?)")
        params.extend([f"%{search}%"] * 3)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(f"SELECT COUNT(*) as cnt FROM constructclaw_incident {where}", params).fetchone()["cnt"]
    rows = conn.execute(
        f"SELECT * FROM constructclaw_incident {where} ORDER BY incident_date DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    ok({"incidents": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# close-incident
# ---------------------------------------------------------------------------
def close_incident(conn, args):
    inc_id = getattr(args, "incident_id", None)
    if not inc_id:
        err("--incident-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_incident")).select(Table("constructclaw_incident").star).where(Field("id") == P()).get_sql(), (inc_id,)).fetchone()
    if not row:
        err(f"Incident {inc_id} not found")
    if row["incident_status"] == "closed":
        err("Incident is already closed")

    conn.execute(
        "UPDATE constructclaw_incident SET incident_status = 'closed', updated_at = datetime('now') WHERE id = ?",
        (inc_id,),
    )
    audit(conn, SKILL, "construction-close-incident", "constructclaw_incident", inc_id,
          new_values={"incident_status": "closed"})
    conn.commit()
    ok({"incident_id": inc_id, "incident_status": "closed"})


# ---------------------------------------------------------------------------
# add-toolbox-talk
# ---------------------------------------------------------------------------
def add_toolbox_talk(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "topic", None):
        err("--topic is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    tt_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_toolbox_talk", {"id": P(), "job_id": P(), "talk_date": P(), "topic": P(), "presenter": P(), "attendee_count": P(), "attendees": P(), "duration_minutes": P(), "notes": P(), "company_id": P()})

    conn.execute(sql,
        (
            tt_id, job_id,
            getattr(args, "talk_date", None) or _date.today().isoformat(),
            args.topic,
            getattr(args, "presenter", None),
            int(getattr(args, "attendee_count", None) or 0),
            getattr(args, "attendees", None),
            int(getattr(args, "duration_minutes", None) or 0),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-toolbox-talk", "constructclaw_toolbox_talk", tt_id,
          new_values={"topic": args.topic, "job_id": job_id})
    conn.commit()
    ok({"toolbox_talk_id": tt_id, "job_id": job_id, "topic": args.topic})


# ---------------------------------------------------------------------------
# list-toolbox-talks
# ---------------------------------------------------------------------------
def list_toolbox_talks(conn, args):
    conditions, params = [], []
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM constructclaw_toolbox_talk {where} ORDER BY talk_date DESC", params
    ).fetchall()
    ok({"toolbox_talks": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# add-safety-cert
# ---------------------------------------------------------------------------
def add_safety_cert(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "worker_name", None):
        err("--worker-name is required")
    if not getattr(args, "cert_type", None):
        err("--cert-type is required")

    sc_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_safety_cert", {"id": P(), "job_id": P(), "worker_name": P(), "cert_type": P(), "cert_number": P(), "issued_date": P(), "expiry_date": P(), "issuing_authority": P(), "company_id": P()})

    conn.execute(sql,
        (
            sc_id,
            getattr(args, "job_id", None),
            args.worker_name,
            args.cert_type,
            getattr(args, "cert_number", None),
            getattr(args, "issued_date", None),
            getattr(args, "expiry_date", None),
            getattr(args, "issuing_authority", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-safety-cert", "constructclaw_safety_cert", sc_id,
          new_values={"worker_name": args.worker_name, "cert_type": args.cert_type})
    conn.commit()
    ok({"safety_cert_id": sc_id, "worker_name": args.worker_name,
        "cert_type": args.cert_type, "cert_status": "active"})


# ---------------------------------------------------------------------------
# list-safety-certs
# ---------------------------------------------------------------------------
def list_safety_certs(conn, args):
    conditions, params = [], []
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    wn = getattr(args, "worker_name", None)
    if wn:
        conditions.append("worker_name = ?")
        params.append(wn)
    cs = getattr(args, "cert_status", None)
    if cs:
        conditions.append("cert_status = ?")
        params.append(cs)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM constructclaw_safety_cert {where} ORDER BY expiry_date ASC", params
    ).fetchall()
    ok({"safety_certs": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# expire-safety-cert
# ---------------------------------------------------------------------------
def expire_safety_cert(conn, args):
    sc_id = getattr(args, "safety_cert_id", None)
    if not sc_id:
        err("--safety-cert-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_safety_cert")).select(Table("constructclaw_safety_cert").star).where(Field("id") == P()).get_sql(), (sc_id,)).fetchone()
    if not row:
        err(f"Safety cert {sc_id} not found")
    if row["cert_status"] in ("expired", "revoked"):
        err(f"Cert is already {row['cert_status']}")

    conn.execute(
        "UPDATE constructclaw_safety_cert SET cert_status = 'expired', updated_at = datetime('now') WHERE id = ?",
        (sc_id,),
    )
    audit(conn, SKILL, "construction-expire-safety-cert", "constructclaw_safety_cert", sc_id,
          new_values={"cert_status": "expired"})
    conn.commit()
    ok({"safety_cert_id": sc_id, "cert_status": "expired"})


# ---------------------------------------------------------------------------
# osha-300-summary -- OSHA 300 log summary
# ---------------------------------------------------------------------------
def osha_300_summary(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    conditions = ["company_id = ?", "osha_recordable = 1"]
    params = [args.company_id]

    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)

    start_date = getattr(args, "start_date", None)
    if start_date:
        conditions.append("incident_date >= ?")
        params.append(start_date)
    end_date = getattr(args, "end_date", None)
    if end_date:
        conditions.append("incident_date <= ?")
        params.append(end_date)

    where = f"WHERE {' AND '.join(conditions)}"

    rows = conn.execute(
        f"SELECT * FROM constructclaw_incident {where} ORDER BY incident_date",
        params,
    ).fetchall()

    total_recordable = len(rows)
    total_days_lost = sum(r["days_lost"] or 0 for r in rows)
    by_type = {}
    for r in rows:
        t = r["incident_type"]
        by_type[t] = by_type.get(t, 0) + 1

    lost_time_cases = sum(1 for r in rows if r["incident_type"] == "lost_time")
    fatalities = sum(1 for r in rows if r["incident_type"] == "fatality")

    ok({
        "company_id": args.company_id,
        "total_recordable_incidents": total_recordable,
        "total_days_lost": total_days_lost,
        "lost_time_cases": lost_time_cases,
        "fatalities": fatalities,
        "by_incident_type": by_type,
        "incidents": [row_to_dict(r) for r in rows],
    })


# ---------------------------------------------------------------------------
# safety-dashboard
# ---------------------------------------------------------------------------
def safety_dashboard(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    company_id = args.company_id

    total_incidents = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_incident WHERE company_id = ?",
        (company_id,),
    ).fetchone()["cnt"]

    open_incidents = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_incident WHERE company_id = ? AND incident_status != 'closed'",
        (company_id,),
    ).fetchone()["cnt"]

    recordable = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_incident WHERE company_id = ? AND osha_recordable = 1",
        (company_id,),
    ).fetchone()["cnt"]

    days_lost = conn.execute(
        "SELECT COALESCE(SUM(days_lost), 0) as total FROM constructclaw_incident WHERE company_id = ?",
        (company_id,),
    ).fetchone()["total"]

    toolbox_talks = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_toolbox_talk WHERE company_id = ?",
        (company_id,),
    ).fetchone()["cnt"]

    expiring_certs = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_safety_cert WHERE company_id = ? AND cert_status IN ('expiring_soon','expired')",
        (company_id,),
    ).fetchone()["cnt"]

    by_severity = conn.execute(
        "SELECT severity, COUNT(*) as cnt FROM constructclaw_incident WHERE company_id = ? GROUP BY severity",
        (company_id,),
    ).fetchall()
    severity_breakdown = {r["severity"]: r["cnt"] for r in by_severity}

    ok({
        "company_id": company_id,
        "total_incidents": total_incidents,
        "open_incidents": open_incidents,
        "osha_recordable": recordable,
        "total_days_lost": days_lost,
        "toolbox_talks_conducted": toolbox_talks,
        "expiring_certifications": expiring_certs,
        "by_severity": severity_breakdown,
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-incident": add_incident,
    "construction-update-incident": update_incident,
    "construction-get-incident": get_incident,
    "construction-list-incidents": list_incidents,
    "construction-close-incident": close_incident,
    "construction-add-toolbox-talk": add_toolbox_talk,
    "construction-list-toolbox-talks": list_toolbox_talks,
    "construction-add-safety-cert": add_safety_cert,
    "construction-list-safety-certs": list_safety_certs,
    "construction-expire-safety-cert": expire_safety_cert,
    "construction-osha-300-summary": osha_300_summary,
    "construction-safety-dashboard": safety_dashboard,
}
