import os
from openai import OpenAI

def get_openai_context() -> OpenAI:
    assert os.environ.get('OPENAI_API_KEY'), 'Specify OPENAI_API_KEY in environment variables'
    return OpenAI(api_key=os.environ['OPENAI_API_KEY'])
