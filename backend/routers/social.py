from fastapi import APIRouter, Body

router = APIRouter(prefix='/social', tags=['social'])

@router.post('/caption')
def generate_caption(prompt: str = Body(..., embed=True)):
    # Replace with caption-generation logic using your NLP model or API
    return {
        'prompt': prompt,
        'caption': 'Generated caption placeholder for social media.',
    }
