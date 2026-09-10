from typing import Any
import json
import io
import pandas as pd

import httpx2
import requests
import urllib.request
from mcp.server import MCPServer

mcp = MCPServer("statistik-austria")
client = httpx2.AsyncClient(timeout=30)
DATA_BASE = "https://data.statistik.gv.at"

@mcp.tool()
async def fetch_dataset_json(dataset_id: str) -> dict:
        url = f"{DATA_BASE}/data/{dataset_id}.json"
        result = (await client.get(url))
        result.raise_for_status()
        try:
            raw =  result.json()
            att = raw["extras"]["attribute_description"]
            dimension, measure = [], []
            for attribute in att.split(";"):
                parts = attribute.partition(";")
                code, label = parts[0], parts[2]
                if code.startswith("C-"):
                    target = dimension
                else:
                    target = measure
                target.append({"code": code, "label": label})
            return {"dimension":dimension, "measure": measure}
        except Exception as e:
            return {"error": str(e)}

@mcp.tool()
async def fetch_dataset_csv(dataset_id: str) -> dict:
        url = f"{DATA_BASE}/data/{dataset_id}.csv"
        result = (await client.get(url))
        result.raise_for_status()
        try:
            df = pd.read_csv(io.StringIO(result.text), sep=";")
            return {"rows": df.to_dict(orient="records")}
        except Exception as e:
            return {"error": str(e)}



if __name__ == "__main__":
    mcp.run(transport="stdio")