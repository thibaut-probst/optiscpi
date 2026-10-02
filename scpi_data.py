"""Google Sheets loading and SCPI scoring helpers."""

from __future__ import annotations

import csv
import io
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any

# Paste the Google Sheets document ID here. Leave empty to use sample data.
SHEET_ID = "10RwJl0A2dvoHjY6LmOFQvT7nghF3-n73hf-Aa9FJBtE"
WORKSHEETS = {
    "data": "Data",
    "scores": "Scores",
    "weights": "Pondérations",
}

CATEGORY_ORDER = [
    "Structure financière",
    "Diversification",
    "Sécurité locative",
    "Maturité",
    "Rentabilité",
]
PROFILE_ORDER = ["Équilibre", "Stabilité", "Performance"]
MAX_SHEET_RESPONSE_BYTES = 8 * 1024 * 1024

class SheetLoadError(RuntimeError):
    """Raised when a configured worksheet cannot be loaded."""


def _csv_url(sheet_id: str, worksheet: str) -> str:
    if not sheet_id or any(
        not character.isascii() or not (character.isalnum() or character in "-_")
        for character in sheet_id
    ):
        raise SheetLoadError("L’identifiant du Google Sheet est invalide.")
    encoded_sheet = urllib.parse.quote(worksheet, safe="")
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={encoded_sheet}"
    )
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "docs.google.com":
        raise SheetLoadError("La source Google Sheets doit utiliser HTTPS.")
    return url


def _read_google_csv(sheet_id: str, worksheet: str) -> str:
    request = urllib.request.Request(
        _csv_url(sheet_id, worksheet),
        headers={"User-Agent": "OptiSCPI/1.0"},
    )
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler())
    try:
        with opener.open(request, timeout=12) as response:
            content = response.read(MAX_SHEET_RESPONSE_BYTES + 1)
    except Exception as error:
        raise SheetLoadError(
            f"Impossible de lire l’onglet « {worksheet} » : {error}"
        ) from error

    if len(content) > MAX_SHEET_RESPONSE_BYTES:
        raise SheetLoadError(f"L’onglet « {worksheet} » dépasse la taille autorisée.")
    return content.decode("utf-8-sig")


def _read_sheet(sheet_id: str, worksheet: str) -> list[dict[str, str]]:
    content = _read_google_csv(sheet_id, worksheet)
    rows = list(csv.DictReader(io.StringIO(content)))
    if not rows:
        raise SheetLoadError(f"L’onglet « {worksheet} » est vide ou mal nommé.")
    return [
        {str(key).strip(): (value or "").strip() for key, value in row.items() if key}
        for row in rows
    ]


def _read_fund_details(sheet_id: str, worksheet: str) -> list[dict[str, str]]:
    content = _read_google_csv(sheet_id, worksheet)
    rows = list(csv.reader(io.StringIO(content)))
    return [
        {
            "name": row[1].strip(),
            "debt_rate": row[7].strip(),
            "liquidity_rate": row[8].strip(),
            "discount": row[11].strip(),
        }
        for row in rows[1:117]
        if len(row) > 11 and row[1].strip()
    ]


def load_google_sheet(sheet_id: str, worksheets: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    """Load all configured tabs from a Google Sheet published as CSV."""
    data: dict[str, list[dict[str, str]]] = {}
    for key, tab_name in worksheets.items():
        data[key] = _read_sheet(sheet_id, tab_name)
    return data


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().replace("%", "").replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return default


def _index(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row.get(key, "").strip(): row for row in rows if row.get(key, "").strip()}


def _name_key(value: Any) -> str:
    return " ".join(str(value).casefold().split())


def build_rankings(data: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    """Join the real Google Sheet structure (Data + Scores + weights) or fall back to legacy format."""
    if "scpi" in data and "criteria" in data and "ratings" in data and "weights" in data:
        scpi_by_id = _index(data["scpi"], "scpi_id")
        details_by_name = {
            _name_key(row.get("name", "")): row
            for row in data.get("fund_details", [])
            if row.get("name", "").strip()
        }
        criteria_by_key = _index(data["criteria"], "criterion_key")
        ratings: dict[str, dict[str, float]] = defaultdict(dict)
        for row in data["ratings"]:
            scpi_id = row.get("scpi_id", "").strip()
            criterion_key = row.get("criterion_key", "").strip()
            if scpi_id and criterion_key:
                ratings[scpi_id][criterion_key] = max(0, min(100, _number(row.get("score"))))

        weights: dict[str, dict[str, float]] = defaultdict(dict)
        for row in data["weights"]:
            profile = row.get("profile", "").strip()
            criterion_key = row.get("criterion_key", "").strip()
            if profile and criterion_key:
                weights[profile][criterion_key] = max(0, _number(row.get("weight")))

        indicators: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in data["indicators"]:
            scpi_id = row.get("scpi_id", "").strip()
            if scpi_id:
                indicators[scpi_id].append(row)

        results = []
        for scpi_id, scpi in scpi_by_id.items():
            fund_details = details_by_name.get(_name_key(scpi.get("name", "")), {})
            scpi_values = {
                **scpi,
                **{
                    key: value
                    for key, value in fund_details.items()
                    if key != "name" and value.strip()
                },
            }
            scpi_ratings = ratings.get(scpi_id, {})
            category_values: dict[str, list[float]] = defaultdict(list)
            for criterion_key, score in scpi_ratings.items():
                criterion = criteria_by_key.get(criterion_key)
                if criterion:
                    category_values[criterion.get("category", "")].append(score)

            category_scores = {
                category: sum(values) / len(values)
                for category, values in category_values.items()
                if values
            }
            profile_scores = {}
            for profile in PROFILE_ORDER:
                profile_weights = weights.get(profile, {})
                weighted_values = [
                    (scpi_ratings[key], weight)
                    for key, weight in profile_weights.items()
                    if key in scpi_ratings and weight > 0
                ]
                total_weight = sum(weight for _, weight in weighted_values)
                profile_scores[profile] = (
                    sum(score * weight for score, weight in weighted_values) / total_weight
                    if total_weight
                    else 0.0
                )

            results.append(
                {
                    **scpi_values,
                    "scpi_id": scpi_id,
                    "profile_scores": profile_scores,
                    "category_scores": category_scores,
                    "indicators": sorted(
                        indicators.get(scpi_id, []),
                        key=lambda row: _number(row.get("order"), 999),
                    ),
                }
            )
        return results

    rows = data.get("data", [])
    score_rows = data.get("scores", [])
    score_by_name = {
        _name_key(row.get("Catégorie SCPI", "")): row
        for row in score_rows
        if row.get("Catégorie SCPI", "").strip()
    }

    results = []
    for row in rows:
        name = row.get("SCPI", "").strip()
        if not name:
            continue
        code_name = _name_key(name)
        score_row = score_by_name.get(code_name, {})
        profile_map = {
            "Performance": "Note Performance",
            "Stabilité": "Note Stabilité",
            "Équilibre": "Note Equilibre",
        }
        profile_scores = {
            profile: _number(score_row.get(column, 0.0))
            for profile, column in profile_map.items()
        }
        category_scores = {
            "Structure financière": _number(score_row.get("Structure financière", 0.0)),
            "Diversification": _number(score_row.get("Diversification", 0.0)),
            "Sécurité locative": _number(score_row.get("Sécurité locative", 0.0)),
            "Maturité": _number(score_row.get("Maturité", 0.0)),
            "Rentabilité": _number(score_row.get("Rentabilité", 0.0)),
        }
        main_sectors = row.get("Secteurs majoritaires", "").strip() or row.get("Stratégie sectorielle", "").strip()
        main_regions = row.get("Régions majoritaires", "").strip() or row.get("Région majoritaire", "").strip()
        indicators = [
            {"label": "TOF", "value": row.get("TOF", "—"), "unit": "%"},
            {"label": "TOP", "value": row.get("TOP", "—"), "unit": "%"},
            {"label": "Capitalisation", "value": row.get("Capitalisation (M)", "—"), "unit": "M€"},
            {"label": "TRI", "value": row.get("TRI", "—"), "unit": "%"},
            {"label": "Taux de liquidité", "value": row.get("Taux de liquidité", "—"), "unit": "%"},
            {"label": "Taux d’endettement", "value": row.get("Taux d'endettement", "—"), "unit": "%"},
        ]
        item = {
            "scpi_id": _name_key(name).replace(" ", "-"),
            "name": name,
            "manager": "",
            "strategy": row.get("Stratégie sectorielle", "").strip(),
            "market": row.get("Région majoritaire", "").strip(),
            "discount": row.get("Décote", "").strip(),
            "liquidity_rate": row.get("Taux de liquidité", "").strip(),
            "debt_rate": row.get("Taux d'endettement", "").strip(),
            "bonus_louve": row.get("Bonus Louve", "").strip(),
            "tri_demembrement": row.get("TRI Démembrement", "").strip(),
            "duree_tri_demembrement": row.get("Durée TRI Démembrement", "").strip(),
            "souscriptions": row.get("Souscriptions", "").strip(),
            "retraits": row.get("Retraits", "").strip(),
            "valeur_souscription": row.get("Valeur de souscription", "").strip(),
            "valeur_reconstitution": row.get("Valeur de reconstitution", "").strip(),
            "part_de_secteur_majoritaire": row.get("Part de secteur majoritaire", "").strip(),
            "part_logements_idf": row.get("Part de logements en IdF", "").strip(),
            "part_logements_regions": row.get("Part de logements en régions", "").strip(),
            "part_logements_hors_france": row.get("Part de logements hors de  France", "").strip(),
            "part_de_region_majoritaire": row.get("Part de région majoritaire", "").strip(),
            "regions_majoritaires": row.get("Régions majoritaires", "").strip(),
            "tof": row.get("TOF", "").strip(),
            "top": row.get("TOP", "").strip(),
            "tof_top": row.get("TOF-TOP", "").strip(),
            "capitalisation": row.get("Capitalisation", "").strip(),
            "capitalisation_m": row.get("Capitalisation (M)", "").strip(),
            "creation": row.get("Création", "").strip(),
            "frais_entree": row.get("Frais d'entrée", "").strip(),
            "frais_gestion": row.get("Frais de gestion", "").strip(),
            "pga": row.get("PGA", "").strip(),
            "tri": row.get("TRI", "").strip(),
            "walb": row.get("WALB", "").strip(),
            "revalorisation_annuelle_historique": row.get("Revalorisation annuelle moyenne historique", "").strip(),
            "revalorisation_annuelle_recente": row.get("Revalorisation annuelle moyenne récente", "").strip(),
            "nombre_actifs": row.get("Nombre d'actifs", "").strip(),
            "main_sectors": main_sectors,
            "main_regions": main_regions,
            "profile_scores": profile_scores,
            "category_scores": category_scores,
            "indicators": indicators,
        }
        results.append(item)
    return results


def demo_data() -> dict[str, list[dict[str, str]]]:
    """Return realistic sample rows so the app works before sheet setup."""
    scpis = [
        ("atlas", "Novaxia NEO", "Novaxia Investissement", "Diversifiée", "Europe", "0,8", "Bureaux · commerces", "France · Allemagne"),
        ("iroko", "Iroko Zen", "Iroko", "Diversifiée", "Europe", "2,4", "Commerces · logistique", "France · Espagne"),
        ("remake", "Remake Live", "Remake AM", "Diversifiée", "Europe", "1,6", "Bureaux · hôtellerie", "Royaume-Uni · France"),
        ("corum", "Corum Origin", "Corum AM", "Diversifiée", "International", "-0,4", "Commerces · bureaux", "Pays-Bas · Italie"),
        ("primopierre", "Primopierre", "Primonial REIM", "Bureaux", "France", "-8,2", "Bureaux · santé", "Île-de-France · régions"),
    ]
    criteria = [
        ("debt", "Endettement", "Structure financière"),
        ("cash", "Trésorerie", "Structure financière"),
        ("sector", "Diversité sectorielle", "Diversification"),
        ("geography", "Diversité géographique", "Diversification"),
        ("occupancy", "Occupation financière", "Sécurité locative"),
        ("tenant", "Qualité des locataires", "Sécurité locative"),
        ("fund_age", "Historique du fonds", "Maturité"),
        ("portfolio", "Taille du patrimoine", "Maturité"),
        ("yield", "Distribution", "Rentabilité"),
        ("price", "Prix et valeur", "Rentabilité"),
    ]
    score_sets = [
        [82, 78, 85, 90, 88, 82, 73, 84, 80, 82],
        [78, 85, 79, 86, 92, 88, 70, 77, 88, 83],
        [75, 72, 88, 92, 89, 84, 63, 72, 96, 79],
        [89, 83, 91, 94, 90, 91, 94, 96, 86, 84],
        [70, 75, 68, 60, 82, 78, 91, 94, 76, 75],
    ]
    scpi_rows = []
    rating_rows = []
    indicator_rows = []
    debt_rates = ["12,4", "8,7", "11,2", "16,8", "28,5"]
    liquidity_rates = ["4,2", "3,7", "2,9", "3,4", "6,1"]
    for index, (scpi_id, name, manager, strategy, market, discount, main_sectors, main_regions) in enumerate(scpis):
        scpi_rows.append(
            {
                "scpi_id": scpi_id,
                "name": name,
                "manager": manager,
                "strategy": strategy,
                "market": market,
                "discount": discount,
                "debt_rate": debt_rates[index],
                "liquidity_rate": liquidity_rates[index],
                "main_sectors": main_sectors,
                "main_regions": main_regions,
                "description": "Données d’exemple à remplacer par votre Google Sheet.",
            }
        )
        for (criterion_key, _, _), score in zip(criteria, score_sets[index]):
            rating_rows.append(
                {"scpi_id": scpi_id, "criterion_key": criterion_key, "score": str(score)}
            )
        metrics = [
            ("Distribution", ["6,51", "7,32", "7,50", "6,50", "5,28"], "%"),
            ("TOF", ["98,6", "97,8", "98,4", "96,2", "91,8"], "%"),
            ("Capitalisation", ["390", "1 100", "650", "3 600", "3 400"], "M€"),
            ("Prix de part", ["187", "204", "204", "1 135", "208"], "€"),
        ]
        for order, (label, values, unit) in enumerate(metrics, start=1):
            indicator_rows.append(
                {
                    "scpi_id": scpi_id,
                    "label": label,
                    "value": values[index],
                    "unit": unit,
                    "order": str(order),
                }
            )

    criteria_rows = [
        {"criterion_key": key, "label": label, "category": category}
        for key, label, category in criteria
    ]
    profile_weights = {
        "Équilibre": [8, 8, 10, 10, 12, 10, 8, 8, 14, 12],
        "Stabilité": [12, 12, 8, 8, 16, 14, 12, 10, 4, 4],
        "Performance": [5, 5, 10, 10, 8, 7, 5, 5, 25, 20],
    }
    weight_rows = [
        {"profile": profile, "criterion_key": key, "weight": str(weight)}
        for profile, values in profile_weights.items()
        for (key, _, _), weight in zip(criteria, values)
    ]
    return {
        "scpi": scpi_rows,
        "criteria": criteria_rows,
        "ratings": rating_rows,
        "weights": weight_rows,
        "indicators": indicator_rows,
    }
