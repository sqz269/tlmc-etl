import json
import os
from openai import OpenAI

def get_openai_context() -> OpenAI:
    assert os.environ.get('OPENAI_API_KEY'), 'Specify OPENAI_API_KEY in environment variables'
    return OpenAI(api_key=os.environ['OPENAI_API_KEY'])

def get_completion(context: OpenAI, model: str, prompt: str) -> str:
    response = context.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    response_text = response.choices[0].message.content
    return json.loads(response_text)
