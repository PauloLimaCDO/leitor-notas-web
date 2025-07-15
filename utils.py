import os
import re
import json
import sqlite3
from typing import Dict
import pandas as pd

# Carrega apenas a planilha FILIAIS.csv em memória ao iniciar o módulo
CAMINHO_CSV = os.path.join(os.path.dirname(__file__), 'TABELAS_PROTHEUS', 'FILIAIS.csv')
FILIAIS_DF = None
if os.path.exists(CAMINHO_CSV):
    # Detecta separador automaticamente
    with open(CAMINHO_CSV, 'r', encoding='utf-8') as f:
        primeira_linha = f.readline()
        sep = ';' if ';' in primeira_linha else ','
    FILIAIS_DF = pd.read_csv(CAMINHO_CSV, dtype=str, sep=sep)
    # Corrige coluna com BOM se necessário
    if '\ufeffCNPJ' in FILIAIS_DF.columns:
        FILIAIS_DF = FILIAIS_DF.rename(columns={'\ufeffCNPJ': 'CNPJ'})
else:
    print('Arquivo de filiais não encontrado!')
    FILIAIS_DF = pd.DataFrame()

# Carrega a planilha COND PAGAMENTOS.csv em memória ao iniciar o módulo
CAMINHO_COND_PAGAMENTOS = os.path.join(os.path.dirname(__file__), 'TABELAS_PROTHEUS', 'COND PAGAMENTOS.csv')
COND_PAGAMENTOS_DF = None
if os.path.exists(CAMINHO_COND_PAGAMENTOS):
    import pandas as pd
    COND_PAGAMENTOS_DF = pd.read_csv(CAMINHO_COND_PAGAMENTOS, dtype=str, sep=';', encoding='utf-8')
    # Padroniza nomes das colunas: maiúsculo, sem acentos, sem espaços
    COND_PAGAMENTOS_DF.columns = (
        COND_PAGAMENTOS_DF.columns
        .str.strip()
        .str.upper()
        .str.normalize('NFKD')
        .str.encode('ascii', errors='ignore')
        .str.decode('utf-8')
    )
    # Renomeia para os nomes esperados
    mapeamento = {
        'CODIGO': 'CODIGO',
        'CÓDIGO': 'CODIGO',
        'CDIGO': 'CODIGO',
        'CODIGO': 'CODIGO',
        'COND. PAGTO': 'COND_PAGTO',
        'COND PAGTO': 'COND_PAGTO',
        'DESCRICAO': 'DESCRICAO',
        'DESCRIÇÃO': 'DESCRICAO',
        'DESCRICAO': 'DESCRICAO',
    }
    COND_PAGAMENTOS_DF = COND_PAGAMENTOS_DF.rename(columns=mapeamento)
else:
    COND_PAGAMENTOS_DF = pd.DataFrame()

# Carrega a planilha PRODUTOS.csv em memória ao iniciar o módulo
CAMINHO_PRODUTOS = os.path.join(os.path.dirname(__file__), 'TABELAS_PROTHEUS', 'PRODUTOS.csv')
PRODUTOS_DF = None
if os.path.exists(CAMINHO_PRODUTOS):
    PRODUTOS_DF = pd.read_csv(CAMINHO_PRODUTOS, dtype=str, sep=';', encoding='utf-8')
    # Padroniza nomes das colunas: maiúsculo, sem acentos, sem espaços
    PRODUTOS_DF.columns = (
        PRODUTOS_DF.columns
        .str.strip()
        .str.upper()
        .str.normalize('NFKD')
        .str.encode('ascii', errors='ignore')
        .str.decode('utf-8')
    )
    # Renomeia para os nomes esperados
    mapeamento_prod = {
        'COD PRODUTO': 'COD_PRODUTO',
        'CÓD PRODUTO': 'COD_PRODUTO',
        'CÓDIGO PRODUTO': 'COD_PRODUTO',
        'CÓDIGO': 'COD_PRODUTO',
        'CODIGO': 'COD_PRODUTO',
        'DESCRICAO': 'DESCRICAO',
        'DESCRIÇÃO': 'DESCRICAO',
        'CORRIGIDO': 'CORRIGIDO',
    }
    PRODUTOS_DF = PRODUTOS_DF.rename(columns={k: v for k, v in mapeamento_prod.items() if k in PRODUTOS_DF.columns})
else:
    PRODUTOS_DF = pd.DataFrame()

# ---------------------------------------------------
#  EXTRAÇÃO (“heurísticas básicas”)
# ---------------------------------------------------

REGRAS_PATH = os.path.join(os.path.dirname(__file__), "regras.json")


def extract_cnpjs(texto: str):
    """
    Retorna lista de CNPJs encontrados no texto (apenas dígitos).
    Aceita formatos: xx.xxx.xxx/xxxx-xx, xx.xxx.xxx/xxxx.xx, xx.xxx.xxx/xxxxxx, e apenas 14 dígitos.
    Não captura números com mais de 14 dígitos.
    """
    padrao = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{6}\b|\b\d{14}\b")
    encontrados = padrao.findall(texto)
    cnpjs = []
    for c in encontrados:
        numeros = re.sub(r"[^\d]", "", c)
        if len(numeros) == 14:
            cnpjs.append(numeros)
    # Retorna sem duplicatas, na ordem
    return list(dict.fromkeys(cnpjs))


def extract_datas(texto: str):
    """
    Retorna lista de datas nos formatos DD/MM/AAAA, DD-MM-AAAA, DD.MM.AAAA, DD/MM/AA, DD-MM-AA, DD.MM.AA encontradas no texto.
    """
    padrao = re.compile(r"\b(\d{2}[./-]\d{2}[./-](\d{2,4}))\b")
    datas = padrao.findall(texto)
    return [d[0] for d in datas]


def extract_numero_nota(texto: str):
    """
    Tenta extrair “Número da nota” procurando ocorrências de “Nº” ou “Número:” seguidas de dígitos.
    """
    padrao = re.compile(r"(?:N[ºo]\s*[:\-]?\s*|\bNúmero\s*[:\-]?\s*)(\d+)")
    m = padrao.search(texto)
    if m:
        return m.group(1)
    return ""


def extract_values(texto: str):
    """
    Retorna lista de valores monetários encontrados (como float).
    Ex.: “1.234,56” → 1234.56
    Ordena do maior para o menor (supõe que primeiro valor seja “Valor Total”).
    """
    padrao = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})")
    encontrados = padrao.findall(texto)
    valores = []
    for v in encontrados:
        num = v.replace(".", "").replace(",", ".")
        try:
            valores.append(float(num))
        except ValueError:
            continue
    # Ordena do maior para o menor (Valor total primeiro)
    valores.sort(reverse=True)
    return valores


# ---------------------------------------------------
#  REGRAS “APRENDIDAS”
# ---------------------------------------------------

REGRAS_PATH = os.path.join(os.path.dirname(__file__), "regras.json")


def carregar_todas_regras() -> list:
    """
    Lê o arquivo regras.json e retorna sempre uma lista de regras.
    Caso o JSON seja um dicionário com chave "regras", devolve esse conteúdo.
    Se for uma lista normal, apenas retorna a própria lista.
    Se estiver vazio ou malformado, retorna [].
    """
    if not os.path.exists(REGRAS_PATH):
        with open(REGRAS_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)
        return []

    try:
        with open(REGRAS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Se o JSON tiver estrutura {"regras": [ ... ]}, devolve a lista interna
        if isinstance(data, dict) and "regras" in data and isinstance(data["regras"], list):
            return data["regras"]
        # Se já for lista, devolve diretamente
        elif isinstance(data, list):
            return data
        else:
            return []
    except (json.JSONDecodeError, IOError):
        return []


def salvar_todas_regras(lista_regras: list):
    """
    Salva lista de regras no arquivo. Aqui vamos gravar DIRETO como array de objetos.
    Se você quiser manter compatibilidade com formato {"regras": [...]}, pode ajustar aqui.
    """
    with open(REGRAS_PATH, "w", encoding="utf-8") as f:
        json.dump(lista_regras, f, indent=2, ensure_ascii=False)


def aplicar_regras_no_registro(registro: Dict[str, str], texto_extraido: str) -> Dict[str, str]:
    """
    Percorre todas as regras carregadas e, se todos os critérios de uma regra
    baterem com os valores em `registro` (ou no texto), aplica `valor_correto`.
    """
    regras = carregar_todas_regras()
    for regra in regras:
        # Cada regra deve ser um dicionário com chaves: "campo", "criterios", "valor_correto"
        if not isinstance(regra, dict):
            continue

        campo = regra.get("campo")
        criterios = regra.get("criterios", {})
        valor_correto = regra.get("valor_correto", "")

        todos_ok = True
        for chave, valor_criterio in criterios.items():
            if chave == "trecho_texto_regex":
                try:
                    if re.search(valor_criterio, texto_extraido, re.IGNORECASE) is None:
                        todos_ok = False
                        break
                except re.error:
                    todos_ok = False
                    break
            else:
                # compara diretamente string → se não bater, falha
                if registro.get(chave, "") != valor_criterio:
                    todos_ok = False
                    break

        if todos_ok and campo in registro:
            registro[campo] = valor_correto

    return registro


def criar_ou_atualizar_regra(campo_alterado: str,
                             registro_antigo: Dict[str, str],
                             registro_corrigido: Dict[str, str],
                             texto_extraido: str):
    """
    Quando o usuário corrige manualmente `campo_alterado` em um registro, cria
    (ou atualiza) uma regra genérica usando:
      - Cnpj_Fornecedor do registro_corrigido
      - tipo_heuristica original (registro_antigo["Tipo"])
      para corrigir aquele mesmo campo em notas futuras.
    """
    lista = carregar_todas_regras()

    # Constroi critérios mínimos:
    criterio = {}
    cnpj_forn = registro_corrigido.get("Cnpj_Fornecedor", "")
    tipo_heur = registro_antigo.get("Tipo", "")

    if cnpj_forn:
        criterio["Cnpj_Fornecedor"] = cnpj_forn
    if tipo_heur:
        criterio["tipo_heuristica"] = tipo_heur

    # Se houver algum trecho marcante, capture via expressão simples (opcional):
    if campo_alterado == "Tipo" and registro_corrigido.get("Tipo") in ["NFC-e", "NFS-e"]:
        m = re.search(r"\bDANFE\s+NFC[- ]?e\b", texto_extraido, re.IGNORECASE)
        if m:
            criterio["trecho_texto_regex"] = r"DANFE\s+NFC[- ]?e"

    nova_regra = {
        "campo": campo_alterado,
        "criterios": criterio,
        "valor_correto": registro_corrigido[campo_alterado]
    }

    # Se já existe regra para mesmo campo+critério, apenas atualize valor_correto
    regra_existente = None
    for r in lista:
        if (
            isinstance(r, dict)
            and r.get("campo") == nova_regra["campo"]
            and r.get("criterios") == nova_regra["criterios"]
        ):
            regra_existente = r
            break

    if regra_existente:
        regra_existente["valor_correto"] = nova_regra["valor_correto"]
    else:
        lista.append(nova_regra)

    salvar_todas_regras(lista)


def extract_cnpj_fornecedor_cliente(texto: str):
    """
    Tenta identificar o CNPJ do fornecedor (emitente) e do cliente (destinatário) usando palavras-chave próximas no texto extraído.
    Refina para ignorar linhas com 'PROTOCOLO DE AUTORIZAÇÃO DE USO' e priorizar o CNPJ correto.
    Retorna (cnpj_fornecedor, cnpj_cliente) como strings (ou vazio se não encontrar).
    """
    texto_lower = texto.lower()
    cnpj_pattern = r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2,3}|\d{14})"
    linhas = texto_lower.splitlines()
    cnpj_fornecedor = ""
    cnpj_cliente = ""
    # 1. Procurar CNPJ do fornecedor (emitente)
    for i, linha in enumerate(linhas):
        if "emitente" in linha or "remetente" in linha or "fornecedor" in linha:
            # Ignora linhas com protocolo
            if "protocolo de autorizacao" in linha or "protocolo de autorização" in linha:
                continue
            cnpjs = re.findall(cnpj_pattern, linha)
            if cnpjs:
                cnpj_fornecedor = cnpjs[0]
                break
            # Procura nas próximas 3 linhas, ignorando protocolo
            for j in range(1, 4):
                if i + j < len(linhas):
                    l = linhas[i + j]
                    if "protocolo de autorizacao" in l or "protocolo de autorização" in l:
                        continue
                    cnpjs = re.findall(cnpj_pattern, l)
                    if cnpjs:
                        cnpj_fornecedor = cnpjs[0]
                        break
        if cnpj_fornecedor:
            break
    # Se não encontrou, tenta pegar o primeiro CNPJ do topo (primeiras 10 linhas, ignorando protocolo)
    if not cnpj_fornecedor:
        for l in linhas[:10]:
            if "protocolo de autorizacao" in l or "protocolo de autorização" in l:
                continue
            cnpjs = re.findall(cnpj_pattern, l)
            if cnpjs:
                cnpj_fornecedor = cnpjs[0]
                break
    # 2. Procurar CNPJ do cliente (destinatário)
    for i, linha in enumerate(linhas):
        if "destinatário" in linha or "cliente" in linha:
            cnpjs = re.findall(cnpj_pattern, linha)
            if cnpjs:
                # Se houver mais de um, pega o último (normalmente à direita)
                cnpj_cliente = cnpjs[-1]
                break
            # Procura nas próximas 3 linhas
            for j in range(1, 4):
                if i + j < len(linhas):
                    cnpjs = re.findall(cnpj_pattern, linhas[i + j])
                    if cnpjs:
                        cnpj_cliente = cnpjs[-1]
                        break
        if cnpj_cliente:
            break
    return cnpj_fornecedor, cnpj_cliente


def extract_nome_fornecedor(texto: str):
    """
    Tenta identificar o nome do fornecedor/emissor/emitente/prestador no texto extraído de PDF/imagem.
    Procura nas primeiras linhas ou próximo de palavras-chave.
    """
    texto_lower = texto.lower()
    linhas = texto.splitlines()
    # 1. Procura nas primeiras 10 linhas (topo do DANFE)
    for l in linhas[:10]:
        if any(palavra in l.lower() for palavra in ["emitente", "remetente", "fornecedor", "prestador", "emit."]):
            # Pega a linha anterior ou a própria linha se for um nome
            idx = linhas.index(l)
            if idx > 0:
                nome = linhas[idx - 1].strip()
                if len(nome) > 3 and not any(x in nome.lower() for x in ["cnpj", "cpf", "inscri", "endereco", "bairro", "municipio", "cep", "data"]):
                    return nome
            # Se não, tenta pegar a própria linha
            nome = l.strip()
            if len(nome) > 3 and not any(x in nome.lower() for x in ["cnpj", "cpf", "inscri", "endereco", "bairro", "municipio", "cep", "data"]):
                return nome
    # 2. Se não achou, pega a primeira linha em caixa alta (provável razão social)
    for l in linhas[:10]:
        if l.isupper() and len(l.strip()) > 3 and not any(x in l.lower() for x in ["cnpj", "cpf", "inscri", "endereco", "bairro", "municipio", "cep", "data"]):
            return l.strip()
    return ""


REGEXS_ESPECIFICOS = {
    "Cnpj_Fornecedor": [
        r'INSCRI[ÇC][ÃA]O ESTADUAL.*?\n.*?CNPJ[:\s]*?(\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2})',
        r'CNPJ[:\s]*?(\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2})',
        r'(?i)(?:prestador|emitente|fornecedor).*?CNPJ[:\s]*?(\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2})',
        r'CNPJ[:\s]*?(\d{2}\.\d{3}\.\d{3}/\d{6})',
        r'\b\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2}\b',
        r'\b\d{2}\.\d{3}\.\d{3}/\d{6}\b',
        r'\b\d{14}\b'
    ],
    "Nome_Fornecedor": [
        r'^[A-Z][A-Z\s&\.]+(?:LTDA|EIRELI|S/A|S\.A\.|S\.A)',
        r'(?<=DANFE\s+DOCUMENTO AUXILIAR DA NOTA FISCAL ELETRÔNICA\n)[A-Z][A-Z\s&\.]+',
        r'(?<=\n)[A-Z][A-Z\s&\.]+(?=\nROD|\nCEP|\nFone|\nCNPJ|\nINSCRI[ÇC][ÃA]O)',
        r'(?i)(?:prestador|emitente|fornecedor).*?:\s*([A-Z][A-Z\s&\.]+)'
    ],
    "Cnpj_Cliente": [
        r'CNPJ/CPF/ID Estrangeiro[:\s]*?(\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2})',
        r'CNPJ/CPF[:\s]*?(\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2})',
        r'(?i)(?:tomador|cliente|destinat[áa]rio).*?CNPJ[:\s]*?(\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2})',
        r'CNPJ[:\s]*?(\d{2}\.\d{3}\.\d{3}/\d{6})',
        r'\b\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2}\b',
        r'\b\d{2}\.\d{3}\.\d{3}/\d{6}\b',
        r'\b\d{14}\b'
    ],
    "Nome_Cliente": [
        r'(?i)(?:tomador|cliente|destinat[áa]rio).*?:\s*([A-Z][A-Z\s&\.]+)'
    ],
    "Numero_Nota": [
        r'Nota Fiscal(?: de Servi[çc]o)?(?: Eletr[ôo]nica)?\s*(?:N[º°]\s*|número\s*|NF[-:]?)\s*(\d{3,})'
    ],
    "Data_Emissao": [
        r'DATA EMISS[ÃA]O[:\s]*?(\d{2}[./-]\d{2}[./-]\d{2,4})',
        r'DATA DE EMISS[ÃA]O[:\s]*?(\d{2}[./-]\d{2}[./-]\d{2,4})',
        r'(?i)data.?de.?emiss[ãa]o[:\s-]*?(\d{2}[./-]\d{2}[./-]\d{2,4})',
        r'(?i)emiss[ãa]o[:\s-]*?(\d{2}[./-]\d{2}[./-]\d{2,4})',
        r'\b\d{2}[./-]\d{2}[./-]\d{2,4}\b'
    ],
    "Data_Vencimento": [
        r'(?i)data.?de.?vencimento[:\s-]*?(\d{2}[./-]\d{2}[./-]\d{2,4})',
        r'(?i)vencimento[:\s-]*?(\d{2}[./-]\d{2}[./-]\d{2,4})',
        r'\b\d{2}[./-]\d{2}[./-]\d{2,4}\b'
    ],
    "Valor_Total": [
        r'(?i)valor.?total(?:.?da.?nota.?fiscal)?[:\s]*?R?\$?\s*([\d.,]+)'
    ],
    "Valor_Liquido": [
        r'(?i)valor.?l[ií]quido(?:.?da.?nota.?fiscal)?[:\s]*?R?\$?\s*([\d.,]+)'
    ],
    "Descricao_Servico": [
        r'(?i)descri[cç][ãa]o.?do.?servi[cç]o[:\s]*?(.*?)\s{2,}',
        r'(?i)discrimina[cç][ãa]o.?do.?servi[cç]o\s*(.*?)\n'
    ],
    "Placa_Veiculo": [
        r'(?i)placa[:\s]*?([A-Z0-9]{7})'
    ],
    "Horario_Data_Saida_Entrada": [
        r'(?i)data.?de.?sa[íi]da[:\s-]*?(\d{2}[./-]\d{2}[./-]\d{2,4})',
        r'(?i)hor[áa]rio.?de.?sa[íi]da[:\s-]*?(\d{2}:\d{2}:\d{2})'
    ],
    "Desconto": [
        r'(?i)desconto[:\s]*?R?\$?\s*([\d.,]+)',
        r'(?i)valor.?do.?desconto[:\s]*?R?\$?\s*([\d.,]+)',
        r'(?i)total.?desconto[:\s]*?\(?R?\$?\)?\s*([\d.,]+)',
        r'(?i)abatimento[:\s]*?R?\$?\s*([\d.,]+)',
        r'(?i)redu[çc][ãa]o[:\s]*?R?\$?\s*([\d.,]+)',
        r'(?i)\(-\)\s*desconto[:\s]*?R?\$?\s*([\d.,]+)',
        r'(?i)\(-\)\s*abatimento[:\s]*?R?\$?\s*([\d.,]+)',
        r'(?i)desconto.*?[\s\n]+([\d.,]+)',
        r'(?i)total\s+desconto\s*\(R\$\)\s*([\d.,]+)',
        r'(?i)desconto\s*\(R\$\)\s*([\d.,]+)'
    ]
}

def extrair_por_regex(texto, campo):
    """
    Tenta extrair o campo usando os regexs específicos. Retorna o primeiro valor encontrado ou ''.
    """
    if campo not in REGEXS_ESPECIFICOS:
        return ""
    for padrao in REGEXS_ESPECIFICOS[campo]:
        m = re.search(padrao, texto, re.MULTILINE | re.IGNORECASE)
        if m:
            if m.lastindex:
                return m.group(1).strip()
            else:
                return m.group(0).strip()
    return ""


def buscar_filial_por_cnpj(cnpj_cliente):
    """
    Busca Grupo, Cod Filial e Filial no DataFrame FILIAIS_DF pelo CNPJ do cliente.
    O CNPJ pode vir mascarado ou não, então remove qualquer máscara antes de buscar.
    Considera CNPJs com 13 dígitos na planilha, adicionando zero à esquerda para comparar.
    Retorna (grupo, cod_filial, filial) ou (None, None, None) se não encontrar.
    """
    try:
        cnpj_limpo = ''.join(filter(str.isdigit, str(cnpj_cliente)))
        # Garante que todos os CNPJs da planilha tenham 14 dígitos (adiciona zero à esquerda se necessário)
        cnpjs_planilha = FILIAIS_DF['CNPJ'].astype(str).apply(lambda x: x.zfill(14))
        linha = FILIAIS_DF[cnpjs_planilha == cnpj_limpo]
        if not linha.empty:
            grupo = linha.iloc[0]['GRUPO']
            cod_filial = linha.iloc[0]['Cod. Filial']
            filial = linha.iloc[0]['Filial']
            return grupo, cod_filial, filial
    except Exception as e:
        print(f'Erro ao buscar filial por CNPJ: {e}')
    return None, None, None


def compute_prazo(data_emissao: str, data_vencimento: str):
    """
    Retorna diferença em dias entre data_emissao e data_vencimento (strings dd/mm/aaaa).
    Se faltar algum, retorna vazio.
    """
    from datetime import datetime
    try:
        d1 = datetime.strptime(data_emissao, "%d/%m/%Y")
        d2 = datetime.strptime(data_vencimento, "%d/%m/%Y")
        delta = (d2 - d1).days
        return str(delta)
    except Exception:
        return ""
