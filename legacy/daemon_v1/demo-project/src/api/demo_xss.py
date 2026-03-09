from flask import Flask, request, render_template_string

app = Flask(__name__)

@app.route('/hello')
def hello():
    name = request.args.get('name', 'World')
    
    # VULNERABLE: SEC004 XSS / SSTI
    # User can pass {{ config.items() }} to see secrets
    return render_template_string("Hello, {{ name }}!", name=name)

@app.route('/unsafe')
def unsafe():
    user_input = request.args.get('input')
    # ALSO VULNERABLE
    return render_template_string("<h1>{{ user_input }}</h1>", user_input=user_input)
