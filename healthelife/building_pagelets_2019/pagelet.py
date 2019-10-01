from flask import Flask, url_for, render_template, request, abort, make_response
import requests
from jose import jwt
from fhirclient import client
import fhirclient.models.patient as fhir_patient
import fhirclient.models.procedure as fhir_procedure


app = Flask(__name__)

if app.config['DEBUG'] == True:
    import os 
    os.environ["PYTHONBREAKPOINT"] = "ipdb.set_trace"
    # import ipdb

TRUSTED_ORIGIN = 'https://chc2019-pageletclass.patientportal.us.healtheintent.com'
MY_ORIGIN = 'https://localpagelet.test:8000'
CERNER_JWKS = 'https://authorization.cerner.com/jwk'
CERNER_EHR_FHIR = 'https://fhir-open.sandboxcerner.com/dstu2/0b8a0111-e8e6-4c26-a91c-5069cbc6b1ca'
CERNER_FPA_URN = 'urn:oid:2.16.840.1.113883.3.13.6'

def process_token(encoded_token):
    keyset = requests.get(CERNER_JWKS).json()
    try:
        token = jwt.decode(encoded_token, keyset,
            audience=MY_ORIGIN,
            issuer=TRUSTED_ORIGIN,
            options= {
                'verify_iat': True,
                'verify_exp': True,
            }
        )

        # OK, this is schenanigans to always "be" a test user in the FHIR sandbox no matter
        # what test user you're really using. You won't do this in a real app :) 
        #
        # http://fhir.cerner.com/millennium/dstu2/individuals/patient/
        token['sub'] = 'URN:CERNER:IDENTITY-FEDERATION:REALM:2E882EFF-FA72-4882-ADC8-A685F7D2BFA6:PRINCIPAL:20A8C75B4900A689D48A72837BF7618B'
        return token

    except (jwt.JWTError, jwt.ExpiredSignatureError, jwt.JWTClaimsError) as e:
        app.logger.info('BCS Token process failure: %s', e)
        abort(403)

    return 

def prevent_clickjacking(response, token):
    response.headers['Content-Security-Policy'] = f"frame-ancestors {token['iss']};"
    response.headers['X-Frame-Options'] = f"allow-from {token['iss']}"

    return response

def smart_server():
    return client.FHIRClient(settings={
        'app_id': 'example',
        'api_base': CERNER_EHR_FHIR
    }).server

def lookup_patient(federated_principal_alias):
    identifier = f'{CERNER_FPA_URN}|{federated_principal_alias}'
    search = fhir_patient.Patient.where(struct={'identifier': identifier})
    patients = search.perform_resources(smart_server())
    
    return {'name': patients[0].name[0].text, 'id': patients[0].id}

def lookup_procedures(patient):
    search =fhir_procedure.Procedure.where(struct={'patient': patient['id']})
    procedures = search.perform_resources(smart_server())

    return [{'name': pro.code.text, 'date': pro.performedDateTime.date} if pro.performedDateTime 
            else {'name': pro.code.text} 
            for pro in procedures]

def format_date(value):
    if value:
        return value.strftime('%Y-%m-%d') 

    return 'No date given.'

app.jinja_env.filters['date'] = format_date

    
@app.route('/')
def procedures():

    try:
        encoded_token = request.args['bcs_token']
    except KeyError:
        abort(400, 'Missing BCS Token!');

    token = process_token(encoded_token)
    patient = lookup_patient(token['sub'])
    procedures = lookup_procedures(patient)

    content = render_template('procedures.html', 
        procedures=procedures,
        stylesheet=url_for('static', filename='style.css')
    )

    response = make_response(content)
    response = prevent_clickjacking(response, token)
    
    return response