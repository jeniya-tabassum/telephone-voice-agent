#!/usr/bin/env python3
"""Debug script to see Kapa API response format"""

import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

async def debug_kapa():
    project_id = os.environ.get("KAPA_PROJECT_ID")
    api_key = os.environ.get("KAPA_API_KEY", "").strip()
    
    url = f"https://api.kapa.ai/query/v1/projects/{project_id}/retrieval/"
    
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": api_key,
    }
    
    payload = {
        "query": "What is Deepgram?",
        "top_k": 3,
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
        print(f"Status: {r.status_code}")
        print(f"Response:\n{r.text[:2000]}")

if __name__ == "__main__":
    asyncio.run(debug_kapa())
