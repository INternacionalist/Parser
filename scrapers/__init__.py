from .hh import scrape_hh_query
from .habr import scrape_habr_query
from .remotejob import scrape_remotejob_query
from .superjob import scrape_superjob_query
from .rabotaru import scrape_rabotaru_query
from .zarplataru import scrape_zarplataru_query

SCRAPERS = {
    "hh": scrape_hh_query,
    "habr": scrape_habr_query,
    "remotejob": scrape_remotejob_query,
    "superjob": scrape_superjob_query,
    "rabotaru": scrape_rabotaru_query,
    "zarplataru": scrape_zarplataru_query,
}

