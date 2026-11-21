# from odoo import models, fields, api


# class gs25_date_check(models.Model):
#     _name = 'gs25_date_check.gs25_date_check'
#     _description = 'gs25_date_check.gs25_date_check'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

