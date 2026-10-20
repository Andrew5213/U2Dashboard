"""Papel timbrado da GatesAir aplicado às páginas dos relatórios.

O timbrado é um PDF **vetorial** (`src/assets/letterhead.pdf`, sem nenhuma imagem
raster), então em vez de redesenhar a logo e a faixa com fpdf2 — que exigiria
exportá-las como imagem e perderia nitidez na impressão — cada página gerada é
sobreposta ao próprio timbrado. A logo sai idêntica ao original, em qualquer zoom.

Por isso os relatórios são **Letter** e não A4: é o formato do timbrado, e esticar
Letter (612×792 pt) para A4 (595×842) distorceria a logo, com fatores diferentes
em x e y.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import pikepdf

from src.core.logging import logger

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
LETTERHEAD_PATH = _ASSETS / "letterhead.pdf"
U2_LOGO_PATH = _ASSETS / "u2-logo.png"

# Medidas do timbrado (mm, página Letter 215.9 × 279.4), medidas no próprio PDF.
# São elas que definem as margens em report_service._Report.
TOP_MM = 37.7        # onde termina a logo / o bloco de endereço
FOOTER_TOP_MM = 266.3  # onde começa a faixa vermelha
SIDE_MM = 12.5       # alinhamento lateral da logo

# A logo da U2 entra à direita da GatesAir, no vão entre ela (acaba em ~72 mm)
# e o bloco de endereço (começa em ~170 mm), centrada na mesma faixa vertical.
U2_X_MM, U2_H_MM = 86.0, 18.0
U2_Y_MM = 15.0
DIVIDER_X_MM = 79.0

# Página Letter em pontos (1 mm = 72/25.4 pt)
PT = 72 / 25.4
PAGE_W_PT, PAGE_H_PT = 215.9 * PT, 279.4 * PT          # retrato
LAND_W_PT, LAND_H_PT = PAGE_H_PT, PAGE_W_PT            # paisagem

_BAND_RGB = (196 / 255, 32 / 255, 50 / 255)            # #C42032, a faixa do rodapé


def _u2_overlay() -> bytes:
    """Página Letter em branco com a logo da U2 e o separador, para sobrepor."""
    from fpdf import FPDF

    page = FPDF(orientation="P", unit="mm", format="Letter")
    page.set_auto_page_break(auto=False)
    page.add_page()
    page.set_draw_color(205, 205, 205)
    page.set_line_width(0.3)
    page.line(DIVIDER_X_MM, U2_Y_MM + 1, DIVIDER_X_MM, U2_Y_MM + U2_H_MM - 1)
    page.image(str(U2_LOGO_PATH), x=U2_X_MM, y=U2_Y_MM, h=U2_H_MM)
    return bytes(page.output())


@lru_cache(maxsize=1)
def _template() -> bytes:
    """O timbrado da GatesAir com a logo da U2 ao lado, montado uma vez por processo.

    A composição é feita aqui, em memória, em vez de num ficheiro novo: o
    `letterhead.pdf` continua a ser exactamente o original que o cliente forneceu.
    """
    base = LETTERHEAD_PATH.read_bytes()
    if not U2_LOGO_PATH.exists():
        logger.warning("Logo da U2 não encontrada - timbrado fica só com a GatesAir")
        return base
    try:
        with pikepdf.open(io.BytesIO(base)) as doc,              pikepdf.open(io.BytesIO(_u2_overlay())) as overlay:
            doc.pages[0].add_overlay(overlay.pages[0])
            out = io.BytesIO()
            doc.save(out)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Falha ao juntar a logo da U2 ao timbrado: {exc}")
        return base


def _landscape_template() -> bytes:
    """O mesmo timbrado numa página deitada, para o Gantt.

    Não dá para girar o timbrado: a logo ficaria de lado. E esticá-lo deformaria
    tanto a logo como o ícone da faixa. Então a página do timbrado é desenhada
    três vezes, recortada: as logos (que ficam à esquerda) e a faixa só descem;
    o bloco de endereço e o ícone da faixa também andam para a direita, para
    continuarem encostados na margem. O vão que sobra na faixa é preenchido com
    a mesma cor — ali ela é lisa.
    """
    import pikepdf

    with pikepdf.open(io.BytesIO(_template())) as src:
        dst = pikepdf.Pdf.new()
        page = dst.add_blank_page(page_size=(LAND_W_PT, LAND_H_PT))
        form = dst.copy_foreign(src.pages[0].as_form_xobject())
        name = page.add_resource(form, pikepdf.Name.XObject)

        dy = LAND_H_PT - PAGE_H_PT          # quanto o topo desce (página mais baixa)
        dx = LAND_W_PT - PAGE_W_PT          # quanto a direita anda (página mais larga)

        # Dois recortes diferentes, e não um só: à esquerda tem de cortar o bloco
        # de endereço (começa em 482 pt); à direita, o que sobra da logo da U2
        # depois de deslocada (acaba em ~505 pt). Um corte único deixaria um
        # pedaço da U2 repetido no meio da página.
        LEFT_CUT = 470.0                    # depois das logos, antes do endereço
        RIGHT_CUT = 600.0                   # depois da U2 deslocada, antes do endereço
        BAND_TOP = 60.0                     # tudo abaixo disto é a faixa do rodapé
        BAND_Y0, BAND_Y1 = 19.25, 37.00     # a faixa, medida no PDF original (pt)
        BAND_X0 = 17.50

        ops = f"""
        q 0 {BAND_TOP} {LEFT_CUT} {LAND_H_PT} re W n 1 0 0 1 0 {dy} cm {name} Do Q
        q {RIGHT_CUT} {BAND_TOP} {LAND_W_PT - RIGHT_CUT} {LAND_H_PT} re W n 1 0 0 1 {dx} {dy} cm {name} Do Q
        q 0 0 {LAND_W_PT} {BAND_TOP} re W n 1 0 0 1 {dx} 0 cm {name} Do Q
        """
        # a faixa deslocada deixa um vão à esquerda; ali ela é lisa, basta pintar.
        # O retângulo entra 2 pt por baixo dela e é 0.3 pt mais alto: a emenda
        # some em vez de virar um fio claro ao arredondar para pixel.
        r, g, b = _BAND_RGB
        ops += (f" q {r} {g} {b} rg {BAND_X0} {BAND_Y0 - 0.15} "
                f"{dx + 2} {BAND_Y1 - BAND_Y0 + 0.3} re f Q ")

        page.contents_add(pikepdf.Stream(dst, ops.encode()), prepend=False)
        out = io.BytesIO()
        dst.save(out)
        return out.getvalue()


@lru_cache(maxsize=1)
def _landscape_cached() -> bytes:
    return _landscape_template()


def stamp(pdf_bytes: bytes, landscape: bool = False) -> bytes:
    """Põe o timbrado por baixo de todas as páginas do PDF.

    `landscape=True` usa a versão deitada, para o Gantt.

    Falha com elegância: se o ficheiro sumir ou o PDF não puder ser aberto, o
    relatório sai sem timbrado em vez de rebentar o download.
    """
    try:
        template_bytes = _landscape_cached() if landscape else _template()
    except OSError as exc:
        logger.warning(f"Timbrado não encontrado ({exc}) - relatório sai sem ele")
        return pdf_bytes

    try:
        with pikepdf.open(io.BytesIO(template_bytes)) as template, \
             pikepdf.open(io.BytesIO(pdf_bytes)) as report:
            source = template.pages[0]
            for page in report.pages:
                # underlay: o timbrado vai por baixo, o conteúdo continua legível
                page.add_underlay(source)
            out = io.BytesIO()
            report.save(out)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001 — um relatório sem timbrado é melhor que nenhum
        logger.error(f"Falha ao aplicar o timbrado: {exc}")
        return pdf_bytes
