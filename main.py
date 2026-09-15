from typing import Any
import io
import pandas as pd

import httpx2
from mcp.server import MCPServer

mcp = MCPServer("statistik-austria")
client = httpx2.AsyncClient(timeout=30)
DATA_BASE = "https://data.statistik.gv.at"

def parse_att(att: str): #helper function to separate attribute descriptions into dimensions and measures
    dimension, measure = [], []
    for attribute in att.split(";"):
        parts = attribute.partition(":")
        code, label = parts[0], parts[2]
        if code.startswith("C-"):
               target = dimension
        else:
               target = measure
        target.append({"code": code, "label": label})
    return dimension, measure
     

@mcp.tool()
async def fetch_dataset_json(dataset_id: str) -> dict:
        """Return the dimension and measure metadata for an OGD dataset. 
        dataset_id is the Statistik Austria dataset identifier (e.g. "OGD_vpi86_VPI_2020_1").
        """
        url = f"{DATA_BASE}/data/{dataset_id}.json"
        resp = (await client.get(url))
        try:
            resp.raise_for_status()
            raw =  resp.json()
            dimension, measure = parse_att(raw["extras"]["attribute_description"])
            return {"dimension":dimension, "measure": measure}
        except Exception as e:
            return {"error": str(e)}

@mcp.tool()
async def fetch_dataset_csv(dataset_id: str) -> dict:
        """Fetch an OGD dataset's full data with coded values resolved to human-readable German labels.
        dataset_id is the Statistik Austria dataset identifier (e.g. "OGD_vpi86_VPI_2020_1").
        """
        url_json = f"{DATA_BASE}/data/{dataset_id}.json"
        url_csv = f"{DATA_BASE}/data/{dataset_id}.csv"
        resp = (await client.get(url_csv))
        try:
            resp.raise_for_status()
            raw_text = (await client.get(url_json)).json()
            dimension, measure = parse_att(raw_text["extras"]["attribute_description"])
            df = pd.read_csv(io.StringIO(resp.text), sep=";")
            for d in dimension:
                 code = d["code"]
                 midcsv = await client.get(f"{DATA_BASE}/data/{dataset_id}_{code}.csv")
                 cdf = pd.read_csv(io.StringIO(midcsv.text), sep=";")
                 df[code] = df[code].map(dict(zip(cdf.iloc[:, 0], cdf.iloc[:, 1]))).fillna(df[code])
            df = df.rename(columns={c["code"]: c["label"] for c in dimension + measure})
            return {"rows": df.to_dict(orient="records")}
        except Exception as e:
            return {"error": str(e)}



if __name__ == "__main__":
    mcp.run(transport="stdio")