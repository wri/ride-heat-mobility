from nairobi_heat_abm.app.main import create_app
import panel as pn

app = create_app()
app.servable()
pn.serve(app, port=5006, show=True)
