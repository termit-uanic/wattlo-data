"""The regions, their queues and where their schedules come from, in the order the sources are tried.

Mirrors core/src/main/kotlin/app/wattlo/Data.kt of the app (the enum Region). A source id is one of:
  yasno       the planned-outages JSON of the YASNO web app (needs yasno=(region id, operator id))
  dtek_data   the JSON files of github.com/Baskerville42/outage-data-ua (needs data_file)
  oe_data     the JSON files of github.com/yaroslav2901/OE_OUTAGE_DATA (needs data_file)
  voe_data    the JSON file of github.com/vn-progr/gpv-voe-vinnytsia (needs data_file)
  bezsvitla   the page of the region on bezsvitla.com.ua (every region has one)
The sites of the power companies themselves (poe.pl.ua for Poltava) do not answer to requests from abroad
(GitHub's runners are in the USA), so they are not here; the app asks poe.pl.ua itself.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

TWELVE = [f"{q}.{n}" for q in range(1, 7) for n in (1, 2)]
KYIV_QUEUES = [f"{i}.1" for i in range(1, 61)]
TERNOPIL_QUEUES = TWELVE + ["7.2", "12.2"]
CHERNIVTSI_QUEUES = [str(i) for i in range(1, 13)]


@dataclass(frozen=True)
class Region:
    slug: str                      # also the page of the region on bezsvitla.com.ua
    name_uk: str
    name_en: str
    queues: list
    sources: Tuple[str, ...]
    yasno: Optional[Tuple[int, int]] = None
    data_file: Optional[str] = None


BZ = "bezsvitla"

REGIONS = [
    Region("poltavska-oblast", "Полтавська область", "Poltava region", TWELVE, (BZ, "oe_data"), data_file="Poltavaoblenergo.json"),
    Region("kharkivska-oblast", "Харківська область", "Kharkiv region", TWELVE, (BZ, "oe_data"), data_file="Kharkivoblenerho.json"),
    Region("dnipropetrovska-oblast", "Дніпропетровська область", "Dnipropetrovsk region", TWELVE,
           ("yasno", "dtek_data", BZ), yasno=(3, 301), data_file="dnipro.json"),
    Region("odeska-oblast", "Одеська область", "Odesa region", TWELVE, ("dtek_data", BZ), data_file="odesa.json"),
    Region("kyivska-oblast", "Київська область", "Kyiv region", TWELVE, ("dtek_data", BZ), data_file="kyiv-region.json"),
    Region("cherkaska-oblast", "Черкаська область", "Cherkasy region", TWELVE, (BZ, "oe_data"), data_file="Cherkasyoblenergo.json"),
    Region("chernihivska-oblast", "Чернігівська область", "Chernihiv region", TWELVE, (BZ, "oe_data"), data_file="Chernihivoblenergo.json"),
    Region("chernivetska-oblast", "Чернівецька область", "Chernivtsi region", CHERNIVTSI_QUEUES, (BZ,)),
    Region("ivano-frankivska-oblast", "Івано-Франківська область", "Ivano-Frankivsk region", TWELVE, (BZ, "oe_data"), data_file="Prykarpattiaoblenerho.json"),
    Region("khmelnytska-oblast", "Хмельницька область", "Khmelnytskyi region", TWELVE, (BZ, "oe_data"), data_file="Khmelnytskoblenerho.json"),
    Region("kirovohradska-oblast", "Кіровоградська область", "Kirovohrad region", TWELVE, (BZ,)),
    Region("lvivska-oblast", "Львівська область", "Lviv region", TWELVE, (BZ, "oe_data"), data_file="Lvivoblenerho.json"),
    Region("mykolaivska-oblast", "Миколаївська область", "Mykolaiv region", TWELVE, (BZ,)),
    Region("rivnenska-oblast", "Рівненська область", "Rivne region", TWELVE, (BZ, "oe_data"), data_file="Rivneoblenergo.json"),
    Region("sumska-oblast", "Сумська область", "Sumy region", TWELVE, (BZ,)),
    Region("ternopilska-oblast", "Тернопільська область", "Ternopil region", TERNOPIL_QUEUES, (BZ,)),
    Region("vinnytska-oblast", "Вінницька область", "Vinnytsia region", TWELVE, (BZ, "voe_data"), data_file="Vinnytsiaoblenerho.json"),
    Region("volynska-oblast", "Волинська область", "Volyn region", TWELVE, (BZ,)),
    Region("zakarpatska-oblast", "Закарпатська область", "Zakarpattia region", TWELVE, (BZ, "oe_data"), data_file="Zakarpattiaoblenerho.json"),
    Region("zaporizka-oblast", "Запорізька область", "Zaporizhzhia region", TWELVE, (BZ, "oe_data"), data_file="Zaporizhzhiaoblenergo.json"),
    Region("zhytomyrska-oblast", "Житомирська область", "Zhytomyr region", TWELVE, (BZ, "oe_data"), data_file="Zhytomyroblenergo.json"),
    Region("kyiv", "Київ", "Kyiv city", KYIV_QUEUES, ("yasno", "dtek_data", BZ), yasno=(25, 902), data_file="kyiv.json"),
]

# where each source lives
RAW_BASE = {
    "dtek_data": "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/",
    "oe_data": "https://raw.githubusercontent.com/yaroslav2901/OE_OUTAGE_DATA/main/data/",
    "voe_data": "https://raw.githubusercontent.com/vn-progr/gpv-voe-vinnytsia/main/data/",
}
SOURCE_INFO = {
    "yasno": ("yasno.ua", "https://yasno.ua/"),
    "dtek_data": ("outage-data-ua (GitHub)", "https://github.com/Baskerville42/outage-data-ua"),
    "oe_data": ("OE_OUTAGE_DATA (GitHub)", "https://github.com/yaroslav2901/OE_OUTAGE_DATA"),
    "voe_data": ("gpv-voe-vinnytsia (GitHub)", "https://github.com/vn-progr/gpv-voe-vinnytsia"),
    "bezsvitla": ("bezsvitla.com.ua", "https://bezsvitla.com.ua/"),
}
