# from odoo import http


# class Gs25Receiving(http.Controller):
#     @http.route('/gs25_receiving/gs25_receiving', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/gs25_receiving/gs25_receiving/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('gs25_receiving.listing', {
#             'root': '/gs25_receiving/gs25_receiving',
#             'objects': http.request.env['gs25_receiving.gs25_receiving'].search([]),
#         })

#     @http.route('/gs25_receiving/gs25_receiving/objects/<model("gs25_receiving.gs25_receiving"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('gs25_receiving.object', {
#             'object': obj
#         })

