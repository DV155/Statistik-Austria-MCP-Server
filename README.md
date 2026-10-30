<a id="readme-top"></a>



<!-- PROJECT LOGO -->
<br />
<div align="center">
  <h3 align="center">Statistik Austria MCP Server</h3>
  <p align="center">An MCP server that gives AI assistants access to Statistik Austria's open data portal</p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#limitations">Limitations</a></li>
      </ul>
    </li>
    <li><a href="#data-source">Data Source</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
  </ol>
</details>

<a id="readme-top"></a>
<!-- mcp-name: io.github.DV155/statistik-austria-mcp -->



<!-- ABOUT THE PROJECT -->
## About The Project

A [Model Context Protocol](https://modelcontextprotocol.io) server for the free Open Government Data portal of Statistik Austria ([data.statistik.gv.at](https://data.statistik.gv.at)). It lets an AI assistant such as Claude search the catalog, read a dataset's structure and fetch its data directly, instead of you downloading and pasting CSV files.

The portal publishes each dataset as a set of files with coded values, so a raw table is hard for a model to read correctly. The server joins the classification files onto the data, so every value arrives as a readable German label together with its original code, and marks the rows that are totals of other rows.

Built as a personal learning project to practise building MCP servers.

Features:
* Keyword search over the full OGD catalog (around 540 datasets)
* Dataset metadata: dimensions and measures
* Data with codes resolved to German labels, formatted `label <code>`
* Total rows are flagged, so the assistant doesn't add a total to its own parts
* Filters by dimension value, so large tables don't have to be read in full
* Paging that never drops rows silently: every response says how many rows exist and where to continue
* Clear messages for datasets in formats the server can't read, instead of a bare error
* Downloads are cached for an hour, so paging through a dataset doesn't download it again

### Built With

* Python 3
* [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
* pandas
* httpx2
* cachetools
* uv

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

The server runs locally on your computer and talks to your MCP client over stdio. `uvx` installs and starts it, so there is nothing to clone for normal use.

### Prerequisites
* [uv](https://docs.astral.sh/uv/getting-started/installation/) (it downloads a matching Python version automatically)
* Git
* Claude Desktop or Claude Code (or any other MCP client)

### Installation

**Claude Desktop**

1. Open the config file. In Claude Desktop, go to Settings → Developer → Edit Config, or open it directly:
   * Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   * macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Add the server
   ```json
   {
     "mcpServers": {
       "statistik-austria": {
         "command": "uvx",
         "args": ["--from", "git+https://github.com/DV155/Statistik-Austria-MCP-Server", "statistik-austria-mcp"]
       }
     }
   }
   ```
3. Quit Claude Desktop completely and start it again.

**Claude Code**

```sh
claude mcp add --transport stdio --scope user statistik-austria -- uvx --from git+https://github.com/DV155/Statistik-Austria-MCP-Server statistik-austria-mcp
```

The first start takes a while, because uv installs the dependencies (pandas is the largest). To get that out of the way, run the `uvx` command above once in a terminal and stop it with Ctrl+C once it is running. If Claude can't find `uvx`, replace `"uvx"` with its full path (`which uvx` shows it). Claude Desktop writes the server's logs to `%APPDATA%\Claude\logs` on Windows and `~/Library/Logs/Claude` on macOS.

**Local development**

1. Clone the repo
   ```sh
   git clone https://github.com/DV155/Statistik-Austria-MCP-Server.git
   cd Statistik-Austria-MCP-Server
   ```
2. Install the dependencies
   ```sh
   uv sync
   ```
3. Start the server in the MCP Inspector
   ```sh
   uv run mcp dev src/statserver/server.py
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE -->
## Usage

Ask Claude a question about Austrian statistics, and it uses the tools on its own.

| Tool | What it does |
| --- | --- |
| `search_dataset` | Searches the catalog by keyword and returns matching dataset IDs and titles |
| `fetch_dataset_json` | Returns a dataset's dimensions and measures with their codes |
| `fetch_dataset_csv` | Returns the data with labels, total-row flags and paging; `filters` keeps only the rows for given dimension values |

The server also provides an `ogd://catalog` resource with the catalog's categories.

Tip: the catalog's titles are German, so the server searches in German. Claude translates the question itself, but asking in German works just as well.

### Limitations

Tested against all 543 datasets in the catalog in October 2026:
* 474 load fully
* 66 are published in formats the server can't read (zip archives and map services such as WFS and WMS); the server says so instead of failing
* 2 contain no data rows
* 1 (`OGDEXT_BINNENWAND_1`) loads without labels and slowly

Other limitations:
* Only the free OGD portal is supported, not the paid STATcube API
* The catalog is read from the portal's HTML page, so search stops working if Statistik Austria changes that page's structure
* The first request for a very large dataset can take several seconds while it downloads

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- DATA SOURCE -->
## Data Source

All data comes from [Statistik Austria - data.statistik.gv.at](https://data.statistik.gv.at), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). When you publish results obtained through this server, credit Statistik Austria as the source.

This is an independent project and is not affiliated with or endorsed by Statistik Austria.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Top contributors:

<a href="https://github.com/DV155/Statistik-Austria-MCP-Server/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=DV155/Statistik-Austria-MCP-Server" alt="contrib.rocks image" />
</a>



<!-- LICENSE -->
## License

Distributed under the MIT license. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Daniil Vasilcovschii - [LinkedIn](https://www.linkedin.com/in/daniil-vasilcovschii-903543358) - [GitHub](https://github.com/DV155)

Project Link: [https://github.com/DV155/Statistik-Austria-MCP-Server](https://github.com/DV155/Statistik-Austria-MCP-Server)

<p align="right">(<a href="#readme-top">back to top</a>)</p>