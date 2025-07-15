from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, after_this_request
from flask_cors import CORS
import os
import pandas as pd
import tempfile
import json
import Identificador
import tabular_notas_openai
import signal
import re
from utils import extract_cnpj_fornecedor_cliente, extrair_por_regex, extract_nome_fornecedor, buscar_filial_por_cnpj, COND_PAGAMENTOS_DF, PRODUTOS_DF
import csv

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

NOTAS_PATH = "notas_salvas.json"
OPENAI_HISTORICO_PATH = "openai_historico.json"
HISTORICO_LIDAS = 'historico_notas_lidas.json'

def carregar_notas():
    if os.path.exists(NOTAS_PATH):
        with open(NOTAS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def salvar_notas(notas):
    with open(NOTAS_PATH, "w", encoding="utf-8") as f:
        json.dump(notas, f, ensure_ascii=False, indent=2)

def carregar_historico_openai():
    if os.path.exists(OPENAI_HISTORICO_PATH):
        with open(OPENAI_HISTORICO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def salvar_historico_openai(historico):
    with open(OPENAI_HISTORICO_PATH, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)

def salvar_historico_lidas(filename, registro):
    try:
        if os.path.exists(HISTORICO_LIDAS):
            with open(HISTORICO_LIDAS, 'r', encoding='utf-8') as f:
                historico = json.load(f)
        else:
            historico = {}
    except Exception:
        historico = {}
    historico[filename] = registro
    with open(HISTORICO_LIDAS, 'w', encoding='utf-8') as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)

def nome_base(filename):
    return os.path.splitext(os.path.basename(filename))[0]

# Função para gerar JSON estruturado via regex (fallback)
def gerar_json_regex(texto, filename):
    from utils import extract_cnpj_fornecedor_cliente, extrair_por_regex
    import re
    cnpj_fornecedor, cnpj_cliente = extract_cnpj_fornecedor_cliente(texto)
    def format_cnpj(cnpj):
        cnpj = re.sub(r'\D', '', cnpj)
        if len(cnpj) == 14:
            return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
        return cnpj
    # Datas
    data_emissao = extrair_por_regex(texto, 'Data_Emissao')
    data_vencimento = extrair_por_regex(texto, 'Data_Vencimento')
    # Prazo
    prazo = ''
    try:
        from utils import compute_prazo
        prazo = compute_prazo(data_emissao, data_vencimento)
    except:
        prazo = ''
    # Produtos: pode-se tentar regex mais avançado aqui se desejar
    produtos = []
    # Tipo heurístico simples
    tipo = ''
    texto_lower = texto.lower()
    if 'serviço' in texto_lower or 'nfs-e' in texto_lower or 'nfs ' in texto_lower:
        tipo = 'NFS-e'
    elif 'danfe' in texto_lower:
        tipo = 'DANFE'
    # Monta JSON apenas com os campos usados no programa
    cnpj_cliente_formatado = format_cnpj(cnpj_cliente)
    grupo, cod_filial, filial = buscar_filial_por_cnpj(cnpj_cliente_formatado)
    return {
        'Arquivo': filename,
        'Cnpj_Fornecedor': format_cnpj(cnpj_fornecedor),
        'Cnpj_Cliente': cnpj_cliente_formatado,
        'Grupo': grupo or '',
        'Cod Filial': cod_filial or '',
        'Filial': filial or '',
        'Numero_Nota': extrair_por_regex(texto, 'Numero_Nota'),
        'Data_Emissao': data_emissao,
        'Data_Vencimento': data_vencimento,
        'Prazo': prazo,
        'Nome_do_Lançador': '',
        'Valor_Total': extrair_por_regex(texto, 'Valor_Total'),
        'Desconto': extrair_por_regex(texto, 'Desconto'),
        'Produtos': produtos,  # Sempre retorna o campo Produtos
        'erro': 'fallback_regex'
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/notas', methods=['GET', 'POST'])
def notas():
    if request.method == 'POST':
        files = request.files.getlist('files')
        saved_files = []
        for file in files:
            filename = file.filename
            path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(path)
            saved_files.append(filename)
        return jsonify({'files': saved_files})
    else:
        files = os.listdir(UPLOAD_FOLDER)
        return jsonify({'files': files})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/dados_nota/<filename>')
def dados_nota(filename):
    key = nome_base(filename)
    historico = carregar_historico_openai()
    if key in historico:
        dado = historico[key]
        # Preencher Grupo, Cod Filial e Filial se houver Cnpj_Cliente
        cnpj_cliente = dado.get('Cnpj_Cliente', '')
        if cnpj_cliente and (not dado.get('Grupo') or not dado.get('Cod Filial') or not dado.get('Filial')):
            grupo, cod_filial, filial = buscar_filial_por_cnpj(cnpj_cliente)
            dado['Grupo'] = grupo or ''
            dado['Cod Filial'] = cod_filial or ''
            dado['Filial'] = filial or ''
        return jsonify(dado)
    # 2. Tenta buscar no JSON salvo
    notas = carregar_notas()
    if filename in notas:
        dado = notas[filename]
        # Preencher Grupo, Cod Filial e Filial se houver Cnpj_Cliente
        cnpj_cliente = dado.get('Cnpj_Cliente', '')
        if cnpj_cliente and (not dado.get('Grupo') or not dado.get('Cod Filial') or not dado.get('Filial')):
            grupo, cod_filial, filial = buscar_filial_por_cnpj(cnpj_cliente)
            dado['Grupo'] = grupo or ''
            dado['Cod Filial'] = cod_filial or ''
            dado['Filial'] = filial or ''
        return jsonify(dado)
    # 3. Se não achou, processa o arquivo original
    path = os.path.join(UPLOAD_FOLDER, filename)
    registro = Identificador.processar_arquivo_identificador(path)
    texto = registro.get('texto_lido', '') or registro.get('Texto_Completo', '') or ''
    # Gera JSON do regex e guarda em memória
    json_regex = gerar_json_regex(texto, filename)
    try:
        # Determina o tipo da nota
        tipo_nota = ''
        if path.lower().endswith('.xml'):
            tipo_nota = 'NFe/XML'
        elif path.lower().endswith('.pdf'):
            if 'serviço' in texto.lower() or 'nfs-e' in texto.lower() or 'nfs ' in texto.lower():
                tipo_nota = 'NFS-e'
            elif 'danfe' in texto.lower():
                tipo_nota = 'DANFE'
            else:
                tipo_nota = 'PDF'
        else:
            tipo_nota = registro.get('Tipo', '') or 'Desconhecido'
        resultado_bruto = tabular_notas_openai.tabular_nota(registro, filename)
        resultado_limpo = tabular_notas_openai.limpar_json_bruto(resultado_bruto)
        dado = json.loads(resultado_limpo)[0]
        # Ajusta Contrato_de_Parceria e produtos
        dado['Contrato_de_Parceria?'] = dado.get('Contrato_de_Parceria', dado.get('Contrato_de_Parceria?', 'NÃO'))
        produtos = dado.get('Produtos', [])
        if not isinstance(produtos, list):
            produtos = [produtos] if produtos else []
        dado['Produtos'] = produtos
        dado['Contrato_de_Parceria?'] = 'SIM' if len(produtos) > 1 else 'NÃO'
        # Preencher automaticamente Grupo, Cod Filial e Filial pelo Cnpj_Cliente
        grupo, cod_filial, filial = buscar_filial_por_cnpj(dado.get('Cnpj_Cliente', ''))
        dado['Grupo'] = grupo or ''
        dado['Cod Filial'] = cod_filial or ''
        dado['Filial'] = filial or ''
        # Remove a inserção do campo 'Tipo' no dado
        # dado['Tipo'] = tipo_nota
        # Formata CNPJ
        for campo in ['Cnpj_Fornecedor', 'Cnpj_Cliente']:
            cnpj = dado.get(campo, '')
            cnpj = re.sub(r'\D', '', cnpj)
            if len(cnpj) == 14:
                cnpj = f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
            dado[campo] = cnpj
        # Se a resposta da OpenAI for vazia ou não trouxer produtos, usa o fallback
        if not dado or not isinstance(dado, dict) or not dado.get('Produtos'):
            return jsonify(json_regex)
        # Salva o JSON tabulado na pasta principal
        json_path = os.path.join(os.path.dirname(__file__), f"{key}_openai.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(dado, f, ensure_ascii=False, indent=2)
        # Salva no histórico
        historico[key] = dado
        salvar_historico_openai(historico)
        return jsonify(dado)
    except Exception as e:
        # Se erro, retorna o JSON do regex
        return jsonify(json_regex)

@app.route('/exportar_excel', methods=['POST'])
def exportar_excel():
    dados = request.get_json()
    linhas = []
    for nota in dados:
        # Lógica para rateio otimizada
        if nota.get('Rateio?') == 'SIM' and any(k.startswith('Rateio_Produto_') for k in nota.keys()):
            idx = 1
            while True:
                prod_rateio = nota.get(f'Rateio_Produto_{idx}')
                if not prod_rateio:
                    break
                linha = nota.copy()
                for k in list(linha.keys()):
                    if k.startswith('Rateio_') or k.startswith('Produto_') or k.startswith('Qtde_') or k.startswith('Valor_Unitario_') or k.startswith('Valor_Total_Produto_') or k.startswith('Descricao_Produto_') or k == 'Produtos':
                        linha.pop(k)
                linha['Produto'] = prod_rateio
                linha['Descricao_Produto'] = nota.get(f'Descricao_Produto_{idx}', prod_rateio)
                linha['Qtde'] = ''
                linha['Valor_Unitario'] = ''
                linha['Valor_Total_Produto'] = ''
                linha['Valor ou %'] = nota.get(f'Rateio_Valor_{idx}', '')
                linha['ContaContabil'] = nota.get(f'Rateio_ContaContabil_{idx}', '')
                linha['CC'] = nota.get(f'Rateio_CC_{idx}', '')
                linha['ItemConta'] = nota.get(f'Rateio_ItemConta_{idx}', '')
                linhas.append(linha)
                idx += 1
        elif nota.get('Produtos'):
            produtos = nota.get('Produtos', [])
            if not isinstance(produtos, list):
                produtos = [produtos] if produtos else []
            for prod in produtos:
                linha = nota.copy()
                for k in list(linha.keys()):
                    if k.startswith('Produto_') or k.startswith('Qtde_') or k.startswith('Valor_Unitario_') or k.startswith('Valor_Total_Produto_') or k.startswith('Descricao_Produto_') or k == 'Produtos':
                        linha.pop(k)
                linha['Produto'] = prod.get('Produto', '')
                linha['Descricao_Produto'] = prod.get('Descricao', '') or prod.get('Produto', '')
                qtde = prod.get('Qtde', '')
                if not qtde or str(qtde).strip() == '':
                    qtde = 1
                linha['Qtde'] = qtde
                linha['Valor_Unitario'] = prod.get('Valor_Unitario', '')
                linha['Valor_Total_Produto'] = prod.get('Valor_Total_Produto', '')
                linhas.append(linha)
        else:
            linha = nota.copy()
            for k in list(linha.keys()):
                if k.startswith('Produto_') or k.startswith('Qtde_') or k.startswith('Valor_Unitario_') or k.startswith('Valor_Total_Produto_') or k.startswith('Descricao_Produto_') or k == 'Produtos':
                    linha.pop(k)
            linha['Produto'] = ''
            linha['Descricao_Produto'] = ''
            linha['Qtde'] = ''
            linha['Valor_Unitario'] = ''
            linha['Valor_Total_Produto'] = ''
            linhas.append(linha)
    # Conversão de valores e números para exportação
    for linha in linhas:
        for campo in ['Valor_Total', 'Valor_Unitario', 'Valor_Total_Produto']:
            if campo in linha:
                valor = str(linha[campo]).replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
                try:
                    linha[campo] = float(valor)
                except:
                    linha[campo] = ''
        if 'Qtde' in linha:
            qtde = str(linha['Qtde']).replace('.', '').replace(',', '.')
            if not qtde or qtde.strip() == '':
                qtde = '1'
            try:
                linha['Qtde'] = float(qtde)
            except:
                linha['Qtde'] = 1
    # Garante que a coluna 'Tipo Rateio' exista em cada linha
    for linha in linhas:
        if linha.get('Rateio?') == 'SIM':
            tipo_rateio = ''
            if 'tipoValorOuPercentual' in linha:
                tipo_rateio = linha['tipoValorOuPercentual']
            elif 'Tipo Rateio' in linha:
                tipo_rateio = linha['Tipo Rateio']
            elif 'tipo_rateio' in linha:
                tipo_rateio = linha['tipo_rateio']
            else:
                tipo_rateio = '%'  # ou 'R$', se preferir um padrão
            linha['Tipo Rateio'] = tipo_rateio
        else:
            linha['Tipo Rateio'] = ''

    # Cria o DataFrame
    df = pd.DataFrame(linhas)

    # Remover colunas sem cabeçalho
    if hasattr(df.columns, 'notnull'):
        df = df.loc[:, df.columns.notnull() & (df.columns != '')]

    # Corrigir 'Descricao_Produto' para não ser igual ao código do produto
    for idx, row in df.iterrows():
        if 'Produto' in df.columns and 'Descricao_Produto' in df.columns:
            if row['Produto'] == row['Descricao_Produto']:
                # Se houver um dicionário de produtos, use-o aqui. Caso contrário, deixe vazio.
                df.at[idx, 'Descricao_Produto'] = ''

    # Remove colunas duplicadas
    if hasattr(df.columns, 'duplicated'):
        df = df.loc[:, ~df.columns.duplicated()]

    # Insere a coluna 'Tipo Rateio' após 'Rateio?'
    if 'Rateio?' in df.columns and 'Tipo Rateio' in df.columns:
        idx = df.columns.get_loc('Rateio?') + 1
        cols = list(df.columns)
        if cols.index('Tipo Rateio') != idx:
            cols.insert(idx, cols.pop(cols.index('Tipo Rateio')))
        df = df[cols]
    
    # Remover apenas a coluna 'tipoValorOuPercentual' se existir
    if 'tipoValorOuPercentual' in df.columns:
        df = df.drop(columns=['tipoValorOuPercentual'])
    
    # Remover a coluna 'Descricao_Produto' se existir
    if 'Descricao_Produto' in df.columns:
        df = df.drop(columns=['Descricao_Produto'])
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    df.to_excel(tmp.name, index=False, engine='openpyxl')
    tmp.close()
    pasta_principal = os.path.dirname(__file__)
    for f in os.listdir(pasta_principal):
        if f.endswith('_openai.json'):
            try:
                os.remove(os.path.join(pasta_principal, f))
            except Exception:
                pass
    @after_this_request
    def cleanup(response):
        for f in os.listdir(UPLOAD_FOLDER):
            try:
                os.remove(os.path.join(UPLOAD_FOLDER, f))
            except Exception:
                pass
        return response
    return send_file(tmp.name, as_attachment=True, download_name='notas_validadas.xlsx')

@app.route('/delete_notas', methods=['POST'])
def delete_notas():
    files_to_delete = request.json.get('files', [])
    for filename in files_to_delete:
        try:
            path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Erro ao deletar {filename}: {e}")
    return jsonify({'status': 'sucesso'})

@app.route('/api/salvar_nota', methods=['POST'])
def salvar_nota():
    nota = request.json  # dicionário completo enviado pelo frontend
    notas = carregar_notas()
    chave = nota.get("Arquivo") or nota.get("id")  # use um campo único
    if not chave:
        return jsonify({"erro": "Chave única (Arquivo ou id) não fornecida"}), 400
    notas[chave] = nota
    salvar_notas(notas)
    return jsonify({"status": "ok"})

@app.route('/api/obter_nota/<chave>', methods=['GET'])
def obter_nota(chave):
    notas = carregar_notas()
    nota = notas.get(chave)
    if nota:
        return jsonify(nota)
    return jsonify({"erro": "Nota não encontrada"}), 404

@app.route('/api/listar_notas', methods=['GET'])
def listar_notas():
    notas = carregar_notas()
    return jsonify(list(notas.values()))

@app.route('/buscar_filial/<cnpj>')
def buscar_filial(cnpj):
    grupo, cod_filial, filial = buscar_filial_por_cnpj(cnpj)
    return jsonify({
        'Grupo': grupo or '',
        'Cod Filial': cod_filial or '',
        'Filial': filial or ''
    })

@app.route('/filiais_por_grupo/<grupo>')
def filiais_por_grupo(grupo):
    from utils import FILIAIS_DF
    if FILIAIS_DF is not None and not FILIAIS_DF.empty:
        filiais = FILIAIS_DF[FILIAIS_DF['GRUPO'] == str(grupo)]
        result = filiais[['Cod. Filial', 'Filial']].drop_duplicates().to_dict(orient='records')
        return jsonify(result)
    return jsonify([])

@app.route('/cond_pagamentos')
def cond_pagamentos():
    if COND_PAGAMENTOS_DF is not None and not COND_PAGAMENTOS_DF.empty:
        return jsonify(COND_PAGAMENTOS_DF[['CODIGO', 'DESCRICAO']].drop_duplicates().to_dict(orient='records'))
    return jsonify([])

@app.route('/descricao_cond_pagamento/<codigo>')
def descricao_cond_pagamento(codigo):
    if COND_PAGAMENTOS_DF is not None and not COND_PAGAMENTOS_DF.empty:
        linha = COND_PAGAMENTOS_DF[COND_PAGAMENTOS_DF['CODIGO'] == str(codigo)]
        if not linha.empty:
            return jsonify({'DESCRICAO': linha.iloc[0]['DESCRICAO']})
    return jsonify({'DESCRICAO': ''})

@app.route('/produtos')
def produtos():
    if PRODUTOS_DF is not None and not PRODUTOS_DF.empty:
        return jsonify(PRODUTOS_DF[['COD_PRODUTO', 'DESCRICAO']].drop_duplicates().to_dict(orient='records'))
    return jsonify([])

@app.route('/descricao_produto/<codigo>')
def descricao_produto(codigo):
    if PRODUTOS_DF is not None and not PRODUTOS_DF.empty:
        linha = PRODUTOS_DF[PRODUTOS_DF['COD_PRODUTO'] == str(codigo)]
        if not linha.empty:
            return jsonify({'DESCRICAO': linha.iloc[0]['DESCRICAO']})
    return jsonify({'DESCRICAO': ''})

@app.route('/contas_contabeis')
def contas_contabeis():
    with open('TABELAS_PROTHEUS/CONTA CONTABIL.csv', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=';')
        # Normaliza os nomes das colunas para remover espaços extras e BOM
        if reader.fieldnames:
            reader.fieldnames = [fn.strip().replace('\ufeff', '') for fn in reader.fieldnames]
        result = []
        for row in reader:
            codigo = row.get('CÓDIGO') or row.get('CODIGO') or row.get('Codigo')
            descricao = row.get('Descricao Conta Contábil') or row.get('DescricaoContaContábil') or row.get('DESCRICAO') or row.get('Descricao') or row.get('DESCRIÇÃO')
            if codigo:
                result.append({'CODIGO': codigo, 'DESCRICAO': descricao or ''})
        return jsonify(result)

@app.route('/cc_reduzido')
def cc_reduzido():
    with open('TABELAS_PROTHEUS/CC REDUZIDO.csv', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        return jsonify([
            {'CCUSTO': row['C. CUSTO'], 'DESCRICAO': row['DESCRIÇÃO']}
            for row in reader if row.get('C. CUSTO')
        ])

@app.route('/itens_conta')
def itens_conta():
    with open('TABELAS_PROTHEUS/ITEM CONTA.csv', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=';')
        # Normaliza os nomes das colunas para remover espaços extras e BOM
        if reader.fieldnames:
            reader.fieldnames = [fn.strip().replace('\ufeff', '') for fn in reader.fieldnames]
        result = []
        for row in reader:
            item = row.get('Item Conta')
            operacao = row.get('Operação')
            if item:
                result.append({'ITEM': item, 'OPERACAO': operacao or ''})
        return jsonify(result)

@app.route('/sair', methods=['POST'])
def sair():
    os._exit(0)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False) 