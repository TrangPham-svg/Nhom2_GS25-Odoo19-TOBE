# from odoo import models, fields, api


# class gs25_replenishment(models.Model):
#     _name = 'gs25_replenishment.gs25_replenishment'
#     _description = 'gs25_replenishment.gs25_replenishment'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

