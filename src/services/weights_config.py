"""
Pesos de disciplinas, atividades e reconstrução de curva de evolução temporal.

Hierarquia:
  Pasta (Província)
    └─ Lista (módulo: Estúdio / Site FM)
         └─ Tarefa = Disciplina (ex.: Obras Civis, Instalações Elétricas)
              └─ Subtarefa = Atividade (ex.: Paredes, Pisos, Tetos)

Critérios usados para atribuição dos pesos (em ordem de peso na decisão):
  - Esforço de trabalho real: o que a atividade fisicamente representa — área/extensão
    coberta, quantidade de unidades, duração típica. Ex.: passagem/roteamento de cabo por
    toda uma sala pesa muito mais que a terminação (solda/crimpagem) de um conector, mesmo
    ambas sendo "cabeamento"; cura de concreto pesa pouco por ser tempo de espera, não
    trabalho ativo; instalação de móveis pesa muito porque sustenta os equipamentos e cobre
    a sala inteira.
  - Complexidade técnica e mão-de-obra especializada
  - Impacto no cronograma (caminho crítico)
  - Risco de retrabalho se executado fora de sequência

Pesos validados via levantamento completo da API do ClickUp (56 listas, 18 províncias, 43
disciplinas reais) e revisão item a item com o responsável do projeto.
"""

import re
import unicodedata
from datetime import datetime


def _norm(text: str) -> str:
    """Normaliza nome para matching: sem acentos, lowercase, só alfanuméricos+espaços."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower().strip()
    cleaned = re.sub(r"[^a-z0-9 ]", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


# ── Pesos relativos das Disciplinas (Tarefas) dentro de cada Lista ────────────
# Valores são relativos — normalizados no cálculo (não precisam somar 1.0).
# Quanto maior o valor, maior a participação no progresso da lista.

TASK_WEIGHTS: dict[str, float] = {
    # ── Padrão "Estúdios" (provincial, português) ─────────────────────────────
    "obras civis": 30.0,  # Obras Civis
    "instalacao de equipamentos do estudio": 25.0,  # Instalação de Equipamentos do Estúdio
    "instalacao de mobiliario acustico do estudio": 20.0,  # Instalação de Mobiliário Acústico do Estúdio
    "testes de pre comissionamento": 10.0,  # Testes de Pré-Comissionamento
    "testes de aceitacao sat": 10.0,  # Testes de Aceitação SAT
    "aceitacao transferencia": 3.0,  # Aceitação Transferência
    "fim das obras": 2.0,  # Fim das Obras

    # ── Padrão "Site FM" ───────────────────────────────────────────────────────
    "instalacao de equipamentos": 30.0,  # Instalação de Equipamentos — núcleo torre/RF do site
    "instalacoes eletricas": 25.0,  # Instalações Elétricas
    "fundacao da base da torre": 20.0,  # Fundação da Base da Torre
    "logistica transporte de conteineres": 7.0,  # Logística - Transporte de Contêineres
    "fechamento de janela": 5.0,  # Fechamento de Janela
    "base de concreto para gerador": 5.0,  # Base de Concreto para Gerador
    "base de concreto para antena satelital": 5.0,  # Base de Concreto para Antena Satelital
    "pintura interna": 3.0,  # Pintura Interna
    "aceitacao e transferencia": 3.0,  # Aceitação e Transferência

    # ── Padrão "CT-Studio / HQ Luanda" (CTP, ESTUDIO CT2/CT3/CT4/CT7/CT11A/CT12…) ─
    "obra civil": 30.0,  # Obra Civil
    "equipamentos": 25.0,  # Equipamentos
    "instalacao acustica": 20.0,  # Instalação Acústica
    "mobiliario": 15.0,  # Mobiliário
    "pre commissioning tests": 10.0,  # Pre Commissioning Tests
    "end of work": 2.0,  # End of Work

    # ── Padrão "Transmissor Luanda Sul" (lista única, disciplinas próprias) ────
    "obra civil predio fase 01 reforma": 20.0,  # Obra Civil Prédio Fase 01 - Reforma
    "instalacao de equipamentos de rf": 18.0,  # Instalação de equipamentos de RF
    "servico de torre fase 02 tx evo": 12.0,  # Serviço de Torre Fase 02 TX - Evo
    "gerador": 10.0,  # Gerador
    "servico antena satelite rx": 10.0,  # Serviço Antena Satélite RX
    "servico torre studio tx 0 9m stl viana radio 5": 8.0,  # Serviço Torre Studio TX 0.9M STL VIANA (Radio 5)
    "servico torre fase 03 rx 0 9m stl viana radio 5": 7.0,  # Serviço Torre Fase 03 RX 0.9M STL VIANA (Radio 5)
    "servico torre fase 03 rx 1 8m stl m o": 7.0,  # Serviço Torre Fase 03 RX 1.8M STL M.O
    "servico de torre fase 01 limpeza evo": 5.0,  # Serviço de Torre Fase 01 Limpeza - Evo
    "entrega projeto": 3.0,  # Entrega Projeto

    # ── Casos isolados ───────────────────────────────────────────────────────
    "infraestrutura eletrica": 40.0,  # Infraestrutura Elétrica
    "infraestrutura de rede": 35.0,  # Infraestrutura de Rede
    "infraestrutura de audio": 25.0,  # Infraestrutura de Audio
    "arte na parede": 3.0,  # Arte na parede
    "termo de encerramento": 2.0,  # Termo de encerramento.

    # ── Padrão HQ Studio (inglês) — visto só na lista modelo "ADMINISTRATIVE",
    # sem uso real ainda; mantido como fallback caso o modelo seja replicado.
    "civil works": 30.0,
    "studio equipment installation": 25.0,
    "studio accoustic furniture installation": 15.0,
    "studio furniture installation": 13.0,
    "sat accepting tests": 5.0,
}


# ── Pesos relativos das Atividades (Subtarefas) por Disciplina ────────────────
# Chave externa: nome normalizado da tarefa pai (disciplina)
# Chave interna: nome normalizado da subtarefa (atividade)
# Fallback automático: peso 1.0 (igual) para nomes não mapeados.
#
# Critério aplicado item a item (não por palavra-chave): o que a atividade
# fisicamente representa. Passagem/roteamento de cabo por toda uma sala pesa
# muito; terminação (solda/crimpagem) e organização de cabo já passado pesam
# pouco — são acabamento técnico rápido, não a corrida física do cabo. Cura de
# concreto pesa pouco por ser tempo de espera. Mobiliário que sustenta os
# equipamentos e cobre a sala inteira pesa muito.

SUBTASK_WEIGHTS: dict[str, dict[str, float]] = {
    "obras civis": {  # Obras Civis
        "paredes": 30.0,  # alvenaria/drywall em toda a sala — maior área
        "pisos": 28.0,  # preparo + revestimento, área comparável à parede
        "instalacoes eletricas": 20.0,  # eletrodutos e fiação embutidos antes de fechar paredes/piso
        "tetos": 15.0,  # área menor que parede/piso
        "demolicoes e remocoes": 7.0,  # trabalho pesado mas de poucos dias, só preparação
    },
    "instalacao de equipamentos do estudio": {  # Instalação de Equipamentos do Estúdio
        "instalacao da mesa de controle": 40.0,  # hub de todas as conexões do estúdio — maior item isolado
        "instalacao de computadores e software": 28.0,  # montagem + config de software de automação
        "instalacao de monitores de audio": 18.0,  # só 2 unidades, tarefa contida
        "instalacao de microfones": 14.0,  # poucos microfones, rápido por posição
    },
    "instalacao de mobiliario acustico do estudio": {  # Instalação de Mobiliário Acústico do Estúdio
        "instalacao de revestimento acustico": 32.0,  # cobre parede/teto inteiro
        "instalacao dos paineis acusticos": 26.0,  # vários painéis, área grande
        "instalacao de ripado nas paredes": 24.0,  # marcenaria de precisão, muitas ripas
        "instalacao das nuvens acusticas": 18.0,  # poucas unidades suspensas
    },
    "testes de pre comissionamento": {  # Testes de Pré-Comissionamento (variantes Estúdio e Site FM)
        "teste de interligacao de equipamentos": 45.0,  # verifica toda a cadeia de sinal
        "teste de sinal de audio": 35.0,  # escopo mais estreito que a interligação completa
        "teste de qualidade de audio": 20.0,  # checagem perceptiva rápida
        "antena e linha de transmissao": 22.0,  # caminho de RF principal — mais complexo de verificar
        "transmissores": 20.0,  # verificação de saída/operação dos transmissores
        "sistema de combinacao fm": 14.0,  # verificação do combinador
        "sistema stl": 14.0,  # verificação do link STL
        "energia e geradores": 10.0,  # checagem de comutação de energia
        "sistema noc": 8.0,  # checagem de conectividade/monitoramento, mais software
        "recepcao de satelite": 6.0,  # sistema único, escopo estreito
        "lista de inventario": 6.0,  # checklist administrativo
    },
    "testes de aceitacao sat": {  # Testes de Aceitação SAT / (SAT) — variantes Estúdio e Site FM
        "verificacao de parametros tecnicos": 45.0,  # checklist técnico amplo
        "teste de qualidade de audio e video": 33.0,  # checagem perceptiva
        "producao de relatorio sat": 22.0,  # administrativo — redigir o relatório
        "antena e linha de transmissao": 22.0,  # mesmo peso do pré-comissionamento
        "transmissores": 20.0,
        "sistema de combinacao fm": 14.0,
        "sistema stl": 14.0,
        "energia e geradores": 10.0,
        "sistema noc": 8.0,
        "recepcao de satelite": 6.0,
        "lista de inventario": 6.0,
    },
    "instalacao de equipamentos": {  # Instalação de Equipamentos — variantes Site FM (torre/RF) e CTP (sala técnica)
        "fm linha de transmissao 4 120 metros": 25.0,  # 120m de linha rígida na torre — o item físico mais longo do site
        "transmissores suportes para tortas e controle n 1": 16.0,  # transmissores + lógica de controle redundante N+1
        "stl linhas de transmissao 1 2": 14.0,  # mesma natureza da linha FM, diâmetro/percurso bem menores
        "sistema de antena fm": 13.0,  # montagem e alinhamento em altura de um único conjunto
        "combinador de 5 vias": 12.0,  # conexões de RF de precisão entre 5 caminhos, calibração
        "sistemas de antenas stl parabolicas de 1 80 m e 0 9 m": 10.0,  # 2 pratos, montagem e apontamento
        "instalacao de antena parabolica": 6.0,  # unidade adicional, escopo contido
        "desidratador": 4.0,  # equipamento pequeno, uma conexão pneumática
        "instalacao de racks": 18.0,  # estrutura que sustenta todos os equipamentos da sala
        "instalacao de rede": 15.0,  # roteamento de cabo de rede pela sala
        "instalacao de audio": 15.0,  # roteamento de cabo de áudio pela sala
        "instalacao de patch de audio": 9.0,  # terminação no patch panel — trabalho de bancada, não roteamento
        "instalacao eletrica": 10.0,  # circuitos elétricos da sala
        "instalacao de ups": 8.0,  # unidade + fiação de bateria
        "instalacao de servidores": 7.0,  # várias unidades para posicionar no rack
        "instalacao de blades": 6.0,  # chassi com várias lâminas, cabeamento interno simplificado
        "instalacao de ciscos": 5.0,  # montagem física + conexão básica
        "instalacao de computadores": 3.0,  # poucas estações nessa sala
        "instalacao de marshall": 2.0,  # um único aparelho de monitoramento
        "instalacao deva": 2.0,  # um único processador
    },
    "instalacoes eletricas": {  # Instalações Elétricas
        "gerador de 165 kva": 22.0,  # equipamento de grande porte — rigging, combustível, exaustão, tie-in, comissionamento
        "sistemas ups unidade de controle e gabinete de baterias": 16.0,  # gabinetes pesados, muitas interligações de bateria
        "sistema de aterramento": 14.0,  # hastes + malha de aterramento ao redor de todo o site
        "bandeja de cabos": 13.0,  # infraestrutura de roteamento por todo o prédio
        "painel de distribuicao ac": 11.0,  # fiação concentrada de um painel, mas com muitos circuitos
        "ar condicionado": 9.0,  # 1-2 unidades, escopo definido
        "chave de transferencia automatica": 7.0,  # um único dispositivo + fiação de controle
        "sistema de exaustao e dutos de ar": 5.0,  # mecânico, mais simples que o AC completo
        "supressor de surtos": 3.0,  # dispositivo único, instalação rápida
    },
    "fundacao da base da torre": {  # Fundação da Base da Torre
        "levantamento da torre": 22.0,  # içamento/montagem da própria estrutura — maior tarefa física isolada
        "derramamento de concreto de fundacao": 20.0,  # concretagem principal
        "preparacao da forma e do reforco para a fundacao da antena parabolica": 16.0,  # forma + armação, comparável ao próprio derramamento
        "estudo de solos e relatorio geotecnico": 10.0,  # levantamento técnico antes da obra
        "cura de concreto": 8.0,  # tempo de espera, pouco trabalho ativo
        "projeto de fundacao": 8.0,  # engenharia/projeto, escritório
        "nivelamento e compactacao do solo": 8.0,  # preparo mecânico do terreno
        "instalacao de acessorios de torre": 6.0,  # ferragens pontuais
    },
    "logistica transporte de conteineres": {  # Logística - Transporte de Contêineres
        "transporte de contentores de viana armazem proef": 40.0,  # logística de longa distância, coordenação e tempo de viagem
        "desembalagem de equipamentos": 35.0,  # abrir e conferir todo o equipamento do site
        "alocacao de equipamentos na sala": 25.0,  # mover itens já desembalados para a posição final
    },
    "fechamento de janela": {  # Fechamento de Janela
        "preenchendo a lacuna com bloco de cimento": 45.0,  # alvenaria — maior parte do trabalho
        "gesso jateado": 35.0,  # camada de acabamento
        "remocao da estrutura existente": 20.0,  # demolição rápida do que existia
    },
    "base de concreto para gerador": {  # Base de Concreto para Gerador
        "derramamento de concreto de fundacao": 35.0,
        "preparacao da forma e da armadura para a fundacao da antena parabolica": 30.0,
        "nivelamento e compactacao do solo": 20.0,
        "cura de concreto": 15.0,  # espera, pouco trabalho ativo
    },
    "base de concreto para antena satelital": {  # Base de Concreto para Antena Satelital
        "derramamento de concreto de fundacao": 35.0,
        "preparacao da forma e da armadura para a fundacao da antena parabolica": 30.0,
        "nivelamento e compactacao do solo": 20.0,
        "cura de concreto": 15.0,
    },
    "pintura interna": {  # Pintura Interna
        "reparo limpeza e preparacao para pintura de paredes e tetos": 40.0,  # geralmente demora mais que a própria pintura
        "pintura de parede": 35.0,  # área maior que o teto
        "pintura de teto": 25.0,  # área menor, trabalho aéreo mais lento por m²
    },
    "obra civil": {  # Obra Civil (CT-Studio)
        "tetos e paredes drywall": 20.0,  # framing + drywall de toda a sala — maior escopo estrutural
        "massa e pintura": 15.0,  # massa corrida + lixamento em várias demãos
        "instalacoes eletricas": 14.0,  # eletrodutos/fiação embutidos antes de fechar drywall
        "instalacao de pisos": 13.0,  # piso da sala inteira (nome usado em parte das listas)
        "pisos acusticos": 13.0,  # mesmo escopo do item acima, nome mais usado nas listas recentes
        "instacao rede de ar condicionado": 10.0,  # duto/tubulação por todo o prédio
        "instalacao rede dos ar condicionados": 10.0,  # mesmo item, nome alternativo pontual
        "instalacao de ar condicionado": 7.0,  # montagem da unidade em si, tarefa contida
        "acabamento de pintura": 7.0,  # demão final, mais rápida que a preparação
        "remocao e demolicao": 6.0,  # preparação, poucos dias
        "instalacao de aquarios": 4.0,  # 1-2 janelas de vidro, escopo pequeno
        "limpeza da area": 3.0,  # rápido, baixa qualificação
        "instalacao de calhas": 2.0,  # item exterior pontual e pequeno
    },
    "equipamentos": {  # Equipamentos (CT-Studio) — passagem de cabo pesa mais que montagem simples
        "passagem de cabos de audio": 14.0,  # roteamento físico do cabo de áudio por toda a sala até cada posição
        "passagem de cabos de rede": 14.0,  # mesmo raciocínio, cabeamento de rede
        "instalacao playlist wheatstone audacity": 13.0,  # config da automação/roteamento de áudio — núcleo técnico do estúdio
        "instalacao computadores": 8.0,  # várias estações de trabalho para posicionar e configurar
        "integracao studios na ctp": 7.0,  # integração e teste com o sistema central
        "instalacao talent station": 6.0,  # montagem da posição de trabalho do apresentador
        "instalacao pedestais suporte microfones re320": 6.0,  # várias posições de microfone
        "instalacao eletrica 220v": 5.0,  # circuito elétrico dedicado a equipamentos
        "instalacao eletrica 110v": 5.0,  # idem, outra tensão
        "instalacao blades": 5.0,  # várias unidades de servidor no rack
        "configuracao de switch cisco": 4.0,  # config técnica de rede, sem esforço físico
        "organizacao de cabos": 4.0,  # amarrar/organizar o que já foi passado — acabamento, não a corrida em si
        "instalacao caixas de som hs5": 3.0,  # só 2 caixas de som, tarefa contida
        "soldagem de cabos de audio": 3.0,  # terminação de conector — bancada, rápido por unidade, acabamento técnico
        "crimpagem de cabos de rede": 3.0,  # mesma lógica da solda: terminação rápida, não a corrida do cabo
        "cabeamento maquina playlist": 3.0,  # corrida de cabo pontual, só a máquina de playlist
        "instalacao switch cisco 9300 48p": 2.0,  # só encaixar no rack, config já contada à parte
        "instalacao angry audio": 2.0,  # um único aparelho de rack
        "instalacao do lxe 2112t e ps1300": 2.0,  # aparelhos pequenos de rack
        "instalacao de reguas de tomada": 2.0,  # montagem simples
        "etiquetagem de cabos": 2.0,  # rápido por etiqueta
        "instalacao playlist": 2.0,  # escopo mais estreito, variante do item de automação acima
        "instalacao notabot": 1.0,  # um único aparelho
        "sincronismo do relogio": 1.0,  # config rápida
        "instalacao de relogio": 1.0,  # pendurar um relógio na parede
        "instalacao on air": 1.0,  # um único letreiro/luz
        "montagem de cadeiras": 1.0,  # montagem rápida por cadeira
    },
    "instalacao acustica": {  # Instalação Acústica (CT-Studio)
        "instalacao de revestimento acustico": 32.0,  # cobre grande área de parede/teto
        "instalacao de portas acusticas": 22.0,  # portas sob medida, pesadas, vedação de precisão — mas só 1-2 unidades
        "instalacao das nuvens acusticas": 18.0,  # várias unidades suspensas
        "instalacao de suporte de nuvens acusticas": 15.0,  # estrutura que antecede a instalação das nuvens
        "instalacao de iluminacao decorativa nos ripados": 13.0,  # elétrica pontual embutida no ripado
    },
    "mobiliario": {  # Mobiliário (CT-Studio) — sustenta os equipamentos, cobre a sala inteira
        "instalacao moveis": 35.0,  # alta contribuição ao progresso visível do estúdio
        "instalacao de ripado nas paredes": 28.0,  # marcenaria de precisão, grande área de parede
        "instalacao de luminaria decorativa no teto": 20.0,  # elétrica + montagem, várias luminárias
        "instalacao de mesas": 10.0,  # subconjunto pontual de Instalação Móveis
        "instalacao de ripado": 7.0,  # variante pontual do item de ripado acima
    },
    "pre commissioning tests": {  # Pre Commissioning Tests (CT-Studio)
        "ligacao de estudio": 45.0,  # verifica toda a interligação do estúdio
        "configuracoes de equipamentos": 35.0,  # ajustes/calibração de equipamentos
        "ligacao de redacao": 20.0,  # escopo menor, usado em menos salas
    },
    "obra civil predio fase 01 reforma": {  # Obra Civil Prédio Fase 01 - Reforma (Transmissor Luanda Sul)
        "instalacao quadros eletricos": 8.0,  # fiação de quadro, técnico e demorado
        "reboco interno externo paredes": 7.0,
        "fechamento paredes": 7.0,
        "montagem piso novo definir": 6.0,
        "instalacao quadro de transferencia do gerador": 6.0,
        "instalacao nova exaustao": 5.0,
        "retirada eletrocalhas paredes": 5.0,  # remoção de infraestrutura antiga de cabeamento
        "retirada dutos exaustao": 5.0,
        "pintura": 5.0,
        "reforma tampas piso definir": 4.0,
        "retirada piso definir": 4.0,
        "instalacao rockstec atrasado": 4.0,
        "fechamento furos paredes": 4.0,
        "limpeza paredes remocao buchas": 4.0,
        "instalacao vidros": 3.0,
        "isolamento salas plastico": 3.0,
        "remocao ar condicionado": 3.0,
        "remocao janelas": 3.0,
        "instalacao luminaria nova definir": 3.0,
        "retirada luminarias teto": 3.0,
        "limpeza calhas piso": 2.0,
        "alinhamento calhas piso": 2.0,
    },
    "instalacao de equipamentos de rf": {  # Instalação de equipamentos de RF (Transmissor Luanda Sul)
        "passagem cabos eletricos": 9.0,  # roteamento de energia por toda a sala técnica
        "passagem cabos dados": 8.0,
        "passagen dos cabos de audio digital": 7.0,
        "passagen dos cabos de audio analogicos": 7.0,
        "posicionamento esteira cabo": 7.0,  # infraestrutura de bandeja que sustenta os cabos
        "posicionamento eletrocalha": 6.0,
        "posicionar transmissores": 6.0,  # movimentação/posicionamento de equipamento pesado
        "posicionar os racks de equipaemntos": 6.0,
        "comissionamento transmissores": 6.0,  # ajuste técnico, não físico
        "posicionamento linha rf": 5.0,
        "posicionar a carga de rf": 4.0,
        "instalacao dos equipamentos de rack": 4.0,
        "posicionar conbiner": 4.0,
        "posicionar os filtros": 4.0,
        "ajuste e aceite do procesador de audio": 4.0,
        "instalacao do processador de audio": 3.0,
        "instalacao de ups": 3.0,
        "conferir ligacoes eletricas": 2.0,  # verificação rápida
        "conferir ligacoes dados": 2.0,
        "conferir medidas posicoes": 2.0,
        "briefing projeto": 1.0,
    },
    "servico de torre fase 02 tx evo": {  # Serviço de Torre Fase 02 TX - Evo
        "subir cabo rf": 14.0,  # içamento de cabo pesado ao longo de toda a torre
        "prender 100 cabo rf": 12.0,  # fixação ao longo de todo o comprimento do cabo
        "subir suporte antena fm": 10.0,
        "subir antena e posicionar o ajuste correto": 10.0,
        "teste conjunto cabo antena": 9.0,
        "montar conectores no cabo de rf": 8.0,  # terminação de precisão, mas pontual
        "teste cabo rf": 8.0,
        "teste vswr antena": 8.0,
        "aterramento cabo rf": 7.0,
        "fixar conforme hci cp": 5.0,
        "conferir balizamento torre": 4.0,
        "teste compressao desidratador rf": 2.0,
    },
    "gerador": {  # Gerador (Transmissor Luanda Sul)
        "passagem de cabos do qgbt ao gerador": 15.0,  # corrida longa de cabo de potência entre dois pontos distantes
        "concretagem base gerador": 12.0,
        "eletrodutos ate qgbt": 11.0,
        "confeccao armacoes": 9.0,
        "check in das ligacoes": 8.0,  # comissionamento/verificação
        "fixacao armacoes": 8.0,
        "aterramento gerador": 7.0,
        "tanque contencao": 7.0,
        "definir fundacao gerador": 6.0,
        "picotar piso base gerador": 6.0,
        "fabricacao caixote": 5.0,
    },
    "servico antena satelite rx": {  # Serviço Antena Satélite RX (Transmissor Luanda Sul)
        "passagem do cabo da antena pelos eletrodutos": 10.0,  # roteamento do cabo por todo o percurso do conduíte
        "escavacao conforme especificacoes do projeto": 9.0,
        "fabricacao da armacao de dentro do concreto": 8.0,
        "confeccao da valeta para passagem do eletroduto no chao": 8.0,
        "instalacao do eletroduto no caminho especificado no projeto": 7.0,
        "confeccao do caixote de madeira para forma do concreto": 6.0,
        "aguardar o tempo de cura do concreto": 5.0,  # tempo de espera, pouco trabalho ativo
        "trava de suporte e nivelacao da antena": 5.0,
        "apontamento da antena conforme satelite especificado no projeto": 5.0,
        "preparacao de cabo para interligar": 4.0,
        "confeccao dos conectores e teste do cabo": 4.0,  # terminação de conector — bancada
        "instalacao haste de aterramento": 4.0,
        "validacao das ligacoes do divisor dentro do rack": 4.0,
        "teste de irds na antena": 4.0,
        "solicitacao a receita do concreto conforme especificacoes do projeto": 3.0,
        "removecao do caixote de madeira": 3.0,
        "definir local da fundacao": 2.0,
    },
    "servico torre studio tx 0 9m stl viana radio 5": {  # Serviço Torre Studio TX 0.9M STL VIANA (Radio 5)
        "fazer ligacoes e conectorizacao": 12.0,  # terminação final de todo o sistema — crítica e abrangente
        "subir o cabo da antena de microondas site": 12.0,
        "subir o cabo da antena de microondas radio": 12.0,
        "instalar os receptores nos racks": 9.0,
        "prender o cabo da antena de microndas site": 9.0,
        "prender o cabo da antena de microndas radio": 9.0,
        "subir antena de microondas site": 8.0,
        "subir antena de microondas radio": 8.0,
        "subir suporte da antena de microondas site": 7.0,
        "subir suporte da antena de microondas radio": 7.0,
    },
    "servico torre fase 03 rx 0 9m stl viana radio 5": {  # Serviço Torre Fase 03 RX 0.9M STL VIANA (Radio 5) — mesmo padrão da Torre TX 0.9M
        "fazer ligacoes e conectorizacao": 12.0,
        "subir o cabo da antena de microondas site": 12.0,
        "subir o cabo da antena de microondas radio": 12.0,
        "instalar os receptores nos racks": 9.0,
        "prender o cabo da antena de microndas site": 9.0,
        "prender o cabo da antena de microndas radio": 9.0,
        "subir antena de microondas site": 8.0,
        "subir antena de microondas radio": 8.0,
        "subir suporte da antena de microondas site": 7.0,
        "subir suporte da antena de microondas radio": 7.0,
    },
    "servico torre fase 03 rx 1 8m stl m o": {  # Serviço Torre Fase 03 RX 1.8M STL M.O — mesmo padrão da Torre TX 0.9M
        "fazer ligacoes e conectorizacao": 12.0,
        "subir o cabo da antena de microondas site": 12.0,
        "subir o cabo da antena de microondas radio": 12.0,
        "instalar os receptores nos racks": 9.0,
        "prender o cabo da antena de microndas site": 9.0,
        "prender o cabo da antena de microndas radio": 9.0,
        "subir antena de microondas site": 8.0,
        "subir antena de microondas radio": 8.0,
        "subir suporte da antena de microondas site": 7.0,
        "subir suporte da antena de microondas radio": 7.0,
    },
    "servico de torre fase 01 limpeza evo": {  # Serviço de Torre Fase 01 Limpeza - Evo
        "retirada dos cabos": 30.0,  # remoção de cabo ao longo de toda a torre
        "retirada das antenas": 30.0,  # desmontagem de equipamento pesado
        "survey organizando cabos": 25.0,
        "limpeza da area": 15.0,
    },
    "termo de encerramento": {  # Termo de encerramento.
        "elaborar termo de encerramento": 10.0,  # único item, sempre 100% do peso do pai
    },
}


# ── Funções de cálculo ────────────────────────────────────────────────────────

def compute_task_progress(
    task_name: str, task_done: bool, subtasks: list[dict]
) -> float:
    """
    Progresso 0..1 de uma disciplina usando pesos das subtarefas.
    - Se o pai está concluído → 1.0 (status do engenheiro é autoritativo).
    - Se não há subtarefas e pai aberto → 0.0.
    - Se há subtarefas e pai aberto → progresso ponderado pelas subtarefas.
    subtasks: [{'name': str, 'is_done': bool}, ...]
    """
    if task_done:
        return 1.0

    if not subtasks:
        return 0.0

    sub_dict = SUBTASK_WEIGHTS.get(_norm(task_name), {})
    total_w = 0.0
    done_w = 0.0
    for sub in subtasks:
        w = sub_dict.get(_norm(sub["name"]), 1.0)
        total_w += w
        if sub["is_done"]:
            done_w += w
    return done_w / total_w if total_w > 0 else 0.0


def compute_list_progress(tasks: list[dict]) -> tuple[float, list[dict]]:
    """
    Progresso ponderado de uma lista (conjunto de disciplinas).
    tasks: [{'name': str, 'is_done': bool, 'subtasks': [...], 'task_id': str}, ...]
    Retorna: (progress 0..1, detalhes por tarefa)
    """
    raw_weights: list[float] = []
    for task in tasks:
        raw_weights.append(TASK_WEIGHTS.get(_norm(task["name"]), 1.0))
    total_w = sum(raw_weights)

    details: list[dict] = []
    weighted_sum = 0.0
    for task, raw_w in zip(tasks, raw_weights):
        norm_w = raw_w / total_w if total_w > 0 else 0.0
        task_prog = compute_task_progress(
            task["name"], task["is_done"], task.get("subtasks", [])
        )
        weighted_sum += norm_w * task_prog

        sub_dict = SUBTASK_WEIGHTS.get(_norm(task["name"]), {})
        sub_raws = [
            sub_dict.get(_norm(s["name"]), 1.0) for s in task.get("subtasks", [])
        ]
        sub_total = sum(sub_raws)
        sub_details = []
        for sub, sw in zip(task.get("subtasks", []), sub_raws):
            sub_details.append({
                "name": sub["name"],
                "is_done": sub["is_done"],
                "weight_raw": sw,
                "weight_norm": sw / sub_total if sub_total > 0 else 0.0,
            })

        details.append({
            "name": task["name"],
            "task_id": task.get("task_id", ""),
            "is_done": task["is_done"],
            "weight_raw": raw_w,
            "weight_norm": norm_w,
            "progress": task_prog,
            "subtasks": sub_details,
        })

    return weighted_sum, details


def compute_province_progress(lists_data: list[dict]) -> dict:
    """
    Calcula progresso ponderado de uma província com pesos de dois níveis.
    lists_data: saída de CacheRepository.get_tasks_for_weighted_progress()

    Retorna estrutura compatível com get_weighted_progress() +
    campo 'task_details' em cada disciplina.
    """
    disciplines: list[dict] = []
    n_lists = len(lists_data)
    folder_progress_sum = 0.0

    simple_total_tasks = 0
    simple_done_tasks = 0

    for lst in lists_data:
        list_prog, task_details = compute_list_progress(lst["tasks"])
        folder_progress_sum += list_prog

        total_tasks = lst["total_tasks"]
        completed = lst["completed_tasks"]
        simple_total_tasks += total_tasks
        simple_done_tasks += completed
        simple_rate = completed / total_tasks if total_tasks > 0 else 0.0

        disciplines.append({
            "list_id": lst["list_id"],
            "name": lst["name"],
            # Cada lista tem peso igual dentro da pasta
            "weight": 1.0 / n_lists if n_lists > 0 else 0.0,
            "weight_pct": round(100.0 / n_lists, 1) if n_lists > 0 else 0.0,
            "completion_rate": round(list_prog, 4),
            "simple_completion_rate": round(simple_rate, 4),
            "total_tasks": total_tasks,
            "completed_tasks": completed,
            "overdue_tasks": lst["overdue_tasks"],
            "weighted_contribution": round(list_prog / n_lists, 4) if n_lists > 0 else 0.0,
            "task_details": task_details,
        })

    folder_weighted = folder_progress_sum / n_lists if n_lists > 0 else 0.0
    simple_progress = simple_done_tasks / simple_total_tasks if simple_total_tasks > 0 else 0.0

    return {
        "disciplines": disciplines,
        "weighted_progress": round(folder_weighted, 4),
        "simple_progress": round(simple_progress, 4),
        "weights_configured": True,
        "weights_sum": 100.0,
    }


def build_province_evolution(lists_data: list[dict], now: datetime) -> dict:
    """
    Reconstrói a curva de progresso ponderado ao longo do tempo para uma província.

    lists_data: saída de CacheRepository.get_folder_tasks_for_evolution() —
        [{list_id, name, total_tasks, completed_tasks, tasks:
            [{task_id, name, is_done, date_created, date_closed, subtasks:[]}]}]

    Retorna:
        {
          "start_date": str | None,     # ISO da data de criação da 1ª tarefa
          "current_progress": float,    # progresso ponderado atual (0-1)
          "points": [{"date": str, "progress": float}]  # série temporal
        }

    Algoritmo:
        - Cada lista tem peso igual: 1/n_lists
        - Dentro de cada lista, tarefas têm peso TASK_WEIGHTS (normalizado)
        - Contribuição de uma tarefa ao progresso da pasta = weight_norm / n_lists
        - Ao marcar uma tarefa como concluída, sua contribuição é adicionada cumulativamente
        - O eixo X é reconstruído a partir de date_closed de cada tarefa concluída
    """
    n_lists = len(lists_data)
    if not n_lists:
        return {"start_date": None, "current_progress": 0.0, "points": []}

    events: list[tuple[datetime, float]] = []   # (date_closed, contribution)
    all_created: list[datetime] = []
    current_progress = 0.0

    for lst in lists_data:
        tasks = lst["tasks"]
        if not tasks:
            continue
        raw_weights = [TASK_WEIGHTS.get(_norm(t["name"]), 1.0) for t in tasks]
        total_w = sum(raw_weights)

        list_prog = 0.0
        for task, raw_w in zip(tasks, raw_weights):
            norm_w = raw_w / total_w if total_w > 0 else 0.0
            contrib = norm_w / n_lists

            if task.get("date_created"):
                all_created.append(task["date_created"])

            if task["is_done"]:
                list_prog += norm_w
                dc = task.get("date_closed")
                if dc:
                    events.append((dc, contrib))

        current_progress += list_prog / n_lists

    start_date = min(all_created) if all_created else None
    events.sort(key=lambda x: x[0])

    points: list[dict] = []
    if start_date:
        points.append({"date": start_date.isoformat(), "progress": 0.0})

    cumulative = 0.0
    for dc, contrib in events:
        cumulative = min(cumulative + contrib, 1.0)
        if start_date is None or dc >= start_date:
            points.append({"date": dc.isoformat(), "progress": round(cumulative, 4)})

    today_iso = now.isoformat()
    if not points or points[-1]["date"] < today_iso:
        points.append({"date": today_iso, "progress": round(current_progress, 4)})

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "current_progress": round(current_progress, 4),
        "points": points,
    }
