import logging
import re

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT id, name FROM gs25_date_check_record ORDER BY id")
    rows = cr.fetchall()
    valid = [(record_id, name) for record_id, name in rows
             if name and re.fullmatch(r"DC-[0-9]+", name)]
    next_number = max((int(name[3:]) for _, name in valid), default=0) + 1
    seen = set()
    for record_id, name in rows:
        if name and re.fullmatch(r"DC-[0-9]+", name) and name not in seen:
            seen.add(name)
            continue
        new_name = f"DC-{next_number:03d}"
        next_number += 1
        cr.execute("UPDATE gs25_date_check_record SET name = %s WHERE id = %s", (new_name, record_id))
        _logger.info("Date Check record %s: %r -> %s", record_id, name, new_name)