"""
Dicionário estático de tradução PT → EN para campos do ClickUp nos relatórios PDF.
Cobre todos os nomes reais encontrados no cache do ClickUp (disciplinas, atividades,
módulos, status) para o projeto U2 Broadcast Angola.
"""

import re
import unicodedata


def _norm(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower().strip()
    cleaned = re.sub(r"[^a-z0-9 ]", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


# Chave: nome normalizado via _norm() — sem acentos, lowercase, só alfanumérico+espaços
# Valor: tradução em inglês
_EN: dict[str, str] = {
    # ── Disciplinas (Tarefas nível superior) ──────────────────────────────────
    "obras civis":                                   "Civil Works",
    "instalacao de equipamentos":                    "Equipment Installation",
    "instalacao de equipamentos do estudio":         "Studio Equipment Installation",
    "instalacao de mobiliario acustico do estudio":  "Studio Acoustic Furniture Installation",
    "instalacao de mobiliario do estudio":           "Studio Furniture Installation",
    "instalacao de equipamentos de transmissao":     "Transmission Equipment Installation",
    "instalacao antenas e cabos":                    "Antenna & Cable Installation",
    "instalacao sistema de energia":                 "Power System Installation",
    "instalacao e comissionamento":                  "Installation & Commissioning",
    "instalacoes eletricas":                         "Electrical Installations",
    "testes de pre comissionamento":                 "Pre-Commissioning Tests",
    "testes de aceitacao sat":                       "SAT Acceptance Tests",
    "testes de aceitacao no site sat":               "On-Site Acceptance Tests (SAT)",
    "testes de fabrica fat":                         "Factory Acceptance Tests (FAT)",
    "aceitacao transferencia":                       "Acceptance & Handover",
    "aceitacao e transferencia":                     "Acceptance & Handover",
    "entrega final e transferencia":                 "Final Delivery & Handover",
    "fim das obras":                                 "End of Works",
    "fundacao da base da torre":                     "Tower Base Foundation",
    "levantamento da torre rf":                      "Tower Erection & RF",
    "logistica transporte de conteineres":           "Container Transport & Logistics",
    "base de concreto para antena satelital":        "Concrete Base for Satellite Antenna",
    "base de concreto para gerador":                 "Concrete Base for Generator",
    "fechamento de janela":                          "Window Closure",
    "pintura interna":                               "Interior Painting",
    "chegada ao porto de luanda":                    "Arrival at Port of Luanda",
    "contrato e ordem de compra":                    "Contract & Purchase Order",
    "desembaraco aduaneiro":                         "Customs Clearance",
    "exportacao e embarque":                         "Export & Shipment",
    "fabricacao e producao dos equipamentos":        "Equipment Manufacturing & Production",
    "transporte para os sites":                      "Transport to Sites",
    "termo de encerramento":                         "Closure Term",

    # ── Atividades (Subtarefas) ───────────────────────────────────────────────
    # Civil Works
    "paredes":                                       "Walls",
    "alvenaria paredes":                             "Masonry / Walls",
    "pisos":                                         "Floors",
    "pavimentos soalho":                             "Floors / Flooring",
    "tetos":                                         "Ceilings",
    "cobertura telhado":                             "Roof / Cover",
    "limpeza":                                       "Cleaning",
    "pintura de teto":                               "Ceiling Painting",
    "pintura de parede":                             "Wall Painting",
    "pintura interior":                              "Interior Painting",
    "pintura exterior":                              "Exterior Painting",
    "gesso jateado":                                 "Spray Plaster",
    "revestimento de paredes":                       "Wall Cladding",
    "caixilharia portas e janelas":                  "Windows & Doors",
    "arranjos exteriores vedacoes":                  "Exterior Arrangements / Fences",
    "canalizacao sanitarios":                        "Plumbing / Restrooms",
    "demolicao preparacao do terreno":               "Demolition / Site Preparation",
    "demolicoes e remocoes":                         "Demolitions & Removals",
    "remocao da estrutura existente":                "Existing Structure Removal",
    "reparo limpeza e preparacao para pintura de paredes e tetos": "Wall & Ceiling Repair, Cleaning & Paint Prep",

    # Tower / Foundation
    "levantamento da torre":                         "Tower Erection",
    "fundacao da base da torre":                     "Tower Base Foundation",
    "fundacao":                                      "Foundation",
    "projeto de fundacao":                           "Foundation Design",
    "escavacao e fundacoes":                         "Excavation & Foundations",
    "estudo de solos e relatorio geotecnico":        "Soil Study & Geotechnical Report",
    "estudo de solo":                                "Soil Study",
    "derramamento de concreto":                      "Concrete Pouring",
    "derramamento de concreto de fundacao":          "Foundation Concrete Pouring",
    "cura de concreto":                              "Concrete Curing",
    "nivelamento":                                   "Leveling",
    "nivelamento e compactacao do solo":             "Ground Leveling & Compaction",
    "preparacao da forma":                           "Formwork Preparation",
    "preparacao da forma e da armadura para a fundacao da antena parabolica": "Formwork & Reinforcement for Parabolic Antenna Foundation",
    "preparacao da forma e do reforco para a fundacao da antena parabolica":  "Formwork & Reinforcement for Parabolic Antenna Foundation",
    "preenchendo a lacuna com bloco de cimento":     "Filling the Gap with Cement Block",
    "bloco de cimento":                              "Cement Block",
    "instalacao de torre mastro":                    "Tower / Mast Installation",
    "instalacao de acessorios de torre":             "Tower Accessories Installation",
    "montagem das antenas":                          "Antenna Assembly",

    # Electrical & Power
    "instalacoes eletricas":                         "Electrical Installations",
    "instalacoes electricas":                        "Electrical Installations",
    "instalacao de quadro eletrico":                 "Electrical Panel Installation",
    "instalacao eletrica control desk":              "Control Desk Electrical Installation",
    "instalacao eletrica da bancada de controlo":    "Control Console Electrical Installation",
    "instalacao eletrica da mesa de controle":       "Control Console Electrical Installation",
    "verificacao de instalacoes eletricas":          "Electrical Installation Verification",
    "painel de distribuicao ac":                     "AC Distribution Panel",
    "chave de transferencia automatica":             "Automatic Transfer Switch",
    "energia e geradores":                           "Power & Generators",
    "instalacao de gerador":                         "Generator Installation",
    "gerador de 165 kva":                            "165KVA Generator",
    "gerador 165kva":                                "165KVA Generator",
    "instalacao de ups baterias":                    "UPS / Battery Installation",
    "sistemas ups unidade de controle e gabinete de baterias": "UPS Systems - Control Unit & Battery Cabinet",
    "sistemas ups":                                  "UPS Systems",
    "sistema de aterramento":                        "Grounding System",
    "aterramento e spda":                            "Grounding & Lightning Protection (SPDA)",
    "supressor de surtos":                           "Surge Suppressor",
    "ar condicionado":                               "Air Conditioning",
    "sistema de exaustao e dutos de ar":             "Exhaust & Air Duct System",
    "bandeja de cabos":                              "Cable Tray",

    # FM Transmission
    "sistema de antena fm":                          "FM Antenna System",
    "sistema antena fm":                             "FM Antenna System",
    "sistema de combinacao fm":                      "FM Combining System",
    "instalacao de antenas tx":                      "TX Antenna Installation",
    "instalacao de combiner":                        "Combiner Installation",
    "combinador de 5 vias":                          "5-Way Combiner",
    "combinador 5 vias":                             "5-Way Combiner",
    "desidratador":                                  "Dehydrator",
    "instalacao do transmissor":                     "Transmitter Installation",
    "transmissores":                                 "Transmitters",
    "transmissores suportes para tortas e controle n 1": "Transmitters, N+1 Supports & Control",
    "transmissores suportes":                        "Transmitter Supports",
    "antena e linha de transmissao":                 "Antenna & Transmission Line",
    "fm linha de transmissao 4 120 metros":          'FM - 4" 120m Transmission Line',
    "stl linhas de transmissao 1 2":                 'STL - 1/2" Transmission Lines',
    "sistema stl":                                   "STL System",
    "sistema noc":                                   "NOC System",
    "sistemas de antenas stl parabolicas de 1 80 m e 0 9 m": "STL Antenna Systems - 1.80m & 0.9m Parabolics",
    "instalacao de antena parabolica":               "Parabolic Antenna Installation",
    "instalacao de cabos rf":                        "RF Cable Installation",
    "tendimento de cabos coaxiais":                  "Coaxial Cable Routing",
    "recepcao de satelite":                          "Satellite Reception",
    "instalacao de conectores e terminais":          "Connectors & Terminals Installation",
    "etiquetagem de cabos e equipamentos":           "Cable & Equipment Labeling",

    # Studio Equipment
    "instalacao de equipamentos do estudio":         "Studio Equipment Installation",
    "instalacao de computadores e software":         "Computer & Software Installation",
    "instalacao computadores":                       "Computer Installation",
    "instalacao de microfones":                      "Microphone Installation",
    "instalacao microfones re320":                   "RE320 Microphone Installation",
    "instalacao de monitores de audio":              "Audio Monitor Installation",
    "instalacao do monitor de audio":                "Audio Monitor Installation",
    "instalacao de monitor de audio speaker":        "Audio Monitor (Speaker) Installation",
    "instalacao speaker audio monitor":              "Speaker Audio Monitor Installation",
    "monitores de audio":                            "Audio Monitors",
    "computadores e software":                       "Computers & Software",
    "mesa de controle":                              "Control Console",

    # Studio Acoustic Furniture
    "instalacao de mobiliario acustico do estudio":  "Studio Acoustic Furniture Installation",
    "instalacao de mobiliario da bancada de controlo": "Control Console Furniture Installation",
    "instalacao de mobiliario da bancada do locutor": "Announcer Console Furniture Installation",
    "instalacao announcer desk furniture":           "Announcer Desk Furniture Installation",
    "instalacao control desk furniture":             "Control Desk Furniture Installation",
    "instalacao da mesa de controle":                "Control Console Installation",
    "instalacao do movel da mesa de controle":       "Control Console Cabinet Installation",
    "instalacao do movel da mesa do locutor":        "Announcer Console Cabinet Installation",
    "instalacao da estacao do apresentador":         "Presenter Station Installation",
    "instalacao da posicao do apresentador talent station": "Presenter Position Installation (Talent Station)",
    "instalacao talent station":                     "Talent Station Installation",
    "instalacao do suporte de microfone boom da mesa do locutor": "Announcer Desk Boom Mic Stand Installation",
    "instalacao mic stand boom control announcer desk": "Mic Stand Boom Installation",

    # Studio Acoustic Treatment
    "instalacao de revestimento acustico":           "Acoustic Cladding Installation",
    "revestimento acustico":                         "Acoustic Cladding",
    "instalacao dos paineis acusticos":              "Acoustic Panel Installation",
    "paineis acusticos":                             "Acoustic Panels",
    "instalacao das nuvens acusticas":               "Acoustic Clouds Installation",
    "nuvens acusticas":                              "Acoustic Clouds",
    "instalacao de ripado nas paredes":              "Wall Batten Installation",
    "instalacao de iluminacao decorativa nos ripados": "Decorative Lighting Installation on Battens",
    "instalacao de luminaria decorativa no teto":    "Decorative Ceiling Lighting Installation",
    "ripado nas paredes":                            "Wall Battens",
    "instalacao de portas acusticas":                "Acoustic Door Installation",

    # Studio Other
    "instalacao angry audio":                        "Angry Audio Installation",
    "instalacao blade ip88 4a":                      "Blade IP88-4A Installation",
    "instalacao blade ip88 4m":                      "Blade IP88-4M Installation",
    "instalacao switch cisco 9300 48p":              "Cisco 9300 48P Switch Installation",
    "instalacao do lxe 2112t":                       "LXE-2112T Installation",
    "instalacao on air signal":                      "On Air Signal Installation",
    "instalacao do sinal de on air":                 "On Air Signal Installation",
    "instalacao wall clock":                         "Wall Clock Installation",
    "instalacao do relogio de parede":               "Wall Clock Installation",
    "instalacao software de automacao playlist":     "Playlist Automation Software Installation",
    "software de automacao":                         "Automation Software",
    "configuracao e testes basicos":                 "Configuration & Basic Tests",
    "alocacao de acessorios":                        "Accessories Allocation",
    "alocacao de equipamentos na sala":              "Equipment Allocation in Room",
    "desembalagem de equipamentos":                  "Equipment Unpacking",
    "desembalagem":                                  "Unpacking",
    "studio power up":                               "Studio Power-Up",
    "ligacao do estudio":                            "Studio Connection",
    "integracao studios na ctp old patch panel":     "Studios Integration at CTP - Old Patch Panel",
    "integracao dos estudios na ctp patch panel antigo": "Studios Integration at CTP - Old Patch Panel",
    "lista de inventario":                           "Inventory List",

    # Testing
    "interligacao de equipamentos":                  "Equipment Interconnection",
    "teste de sinal de audio":                       "Audio Signal Test",
    "qualidade de audio":                            "Audio Quality",
    "qualidade de audio e video":                    "Audio & Video Quality",
    "teste de qualidade de audio":                   "Audio Quality Test",
    "teste de qualidade de audio e video":           "Audio & Video Quality Test",
    "teste de qualidade de sinal rf":                "RF Signal Quality Test",
    "teste de interferencias":                       "Interference Test",
    "teste de interligacao de equipamentos":         "Equipment Interconnection Test",
    "teste de potencia do transmissor":              "Transmitter Power Test",
    "teste de cobertura e alcance":                  "Coverage & Range Test",
    "teste de sistema de energia":                   "Power System Test",
    "verificacao de parametros":                     "Parameter Verification",
    "verificacao de parametros tecnicos":            "Technical Parameters Verification",
    "verificacao de desenhos e tabela de fiacao":    "Drawings & Wiring Table Verification",
    "producao de relatorio sat":                     "SAT Report Production",
    "aoip testes de funcionamento":                  "AoIP Functionality Tests",

    # Logistics
    "logistica transporte de conteineres":           "Container Transport & Logistics",
    "transporte de contentores de viana armazem proef": "Container Transport from Viana (Proef Warehouse)",

    # ── Módulos (Listas) ──────────────────────────────────────────────────────
    "estudio":           "Studio",
    "estudios":          "Studios",
    "studio":            "Studio",
    "site fm":           "FM Site",
    "fm site":           "FM Site",
    "plano de entrega transmissores": "Transmitter Delivery Plan",

    # ── Status ClickUp ────────────────────────────────────────────────────────
    "em andamento":    "In Progress",
    "fazendo":         "In Progress",
    "planejando":      "Planning",
    "nao iniciado":    "Not Started",
    "concluido":       "Completed",
    "revisao":         "Review",
    "em revisao":      "In Review",
    "aprovacao":       "Approval",
    "em aprovacao":    "In Approval",
    "aguardando":      "Waiting",
    "bloqueado":       "Blocked",
    "cancelado":       "Cancelled",
    "entregue":        "Delivered",
}


def translate(text: str | None, lang: str) -> str:
    """Traduz um campo do ClickUp para inglês. Sem correspondência → retorna original."""
    if not text or lang != "en":
        return text or ""
    return _EN.get(_norm(text), text)


def translate_task_row(row: dict, lang: str) -> dict:
    """Aplica translate() aos campos de nome/lista/pasta/status de um dict de tarefa."""
    if lang == "pt":
        return row
    result = dict(row)
    for field in ("name", "list_name", "folder_name"):
        if field in result and result[field]:
            result[field] = translate(result[field], lang)
    if "status" in result and result["status"]:
        result["status"] = translate(result["status"], lang)
    return result
