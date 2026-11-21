# from odoo import http


# class Gs25Replenishment(http.Controller):
#     @http.route('/gs25_replenishment/gs25_replenishment', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/gs25_replenishment/gs25_replenishment/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('gs25_replenishment.listing', {
#             'root': '/gs25_replenishment/gs25_replenishment',
#             'objects': http.request.env['gs25_replenishment.gs25_replenishment'].search([]),
#         })

#     @http.route('/gs25_replenishment/gs25_replenishment/objects/<model("gs25_replenishment.gs25_replenishment"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('gs25_replenishment.object', {
#             'object': obj
#         })

