from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    sequence = env.ref("gs25_date_check.seq_gs25_date_check_record")
    cr.execute("SELECT COALESCE(MAX(SUBSTRING(name FROM 4)::bigint), 0) FROM gs25_date_check_record WHERE name ~ %s", (r"^DC-[0-9]+$",))
    next_number = cr.fetchone()[0] + 1
    if sequence.number_next_actual < next_number:
        sequence.number_next_actual = next_number