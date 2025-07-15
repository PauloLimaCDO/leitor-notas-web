import openai
import json
import time
import re
import os

# Pega a chave da OpenAI das variáveis de ambiente de forma segura
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY não encontrada nas variáveis de ambiente!")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

PROMPT_BASE = r'''Extraia os campos abaixo para cada nota fiscal do texto a seguir. Identifique também campos similares a: número da nota, data de emissão, data de vencimento, produtos ou serviços (mesmo que estejam com nomes diferentes ou variações).

**Critérios técnicos para identificação dos campos:**
- CNPJ: deve seguir o padrão de 14 dígitos, podendo estar nos formatos xx.xxx.xxx/xxxx-xx, xx.xxx.xxx/xxxxxx, ou apenas 14 dígitos. Regex: \b\d{2}\.\d{3}\.\d{3}/\d{4}[-\.]\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{6}\b|\b\d{14}\b
- Datas (emissão/vencimento): formatos DD/MM/AAAA, DD-MM-AAAA, DD.MM.AAAA, DD/MM/AA, DD-MM-AA, DD.MM.AA. Regex: \b(\d{2}[./-]\d{2}[./-](\d{2,4}))\b. Para o campo Data de Vencimento, procure também por campos com o nome "vencimento" ou variações.
- Número da nota: buscar por "Nº", "N°", "Número:" ou variações seguidas de dígitos. Regex: (?:N[ºo]\s*[:\-]?\s*|\bNúmero\s*[:\-]?\s*)(\d+)
- Valores monetários: buscar valores no formato brasileiro, ex: 1.234,56. Regex: (\d{1,3}(?:\.\d{3})*,\d{2})
- Produtos/serviços: normalmente aparecem em linhas ou blocos com nome, quantidade, valor unitário e valor total próximos um do outro.
- Para o campo Cnpj_Fornecedor, procure o padrão de CNPJ (14 dígitos, com ou sem máscara) que aparece IMEDIATAMENTE após as palavras emitente, fornecedor, emissor, prestador, prestador do serviço ou variações semelhantes. Nunca use CNPJs de outros blocos, cabeçalhos, rodapés, chaves de acesso, etc.
- Para o campo Cnpj_Cliente, procure o padrão de CNPJ (14 dígitos, com ou sem máscara) que aparece IMEDIATAMENTE após as palavras cliente, tomador, tomador de serviço, NOME SACADO ou variações semelhantes. Nunca use CNPJs de outros blocos, cabeçalhos, rodapés, chaves de acesso, etc.

- Arquivo
- Numero_Nota
- Cnpj_Fornecedor
- Cnpj_Cliente
- Data_Emissao
- Data_Vencimento
- Condição_de_Pagamento
- Prazo
- Valor_Total
- Desconto (procure por "Total Desconto", "Desconto (R$)", "Valor do Desconto" ou similar. Se houver, extraia apenas o valor numérico, caso contrário deixe vazio)
- Contrato_de_Parceria (preencha "SIM" se houver mais de um produto ou serviço, caso contrário "NÃO")
- Para cada produto ou serviço encontrado, inclua:
    - Produto
    - Qtde
    - Valor_Unitario
    - Valor_Total_Produto (qtde x valor unitario)

Mesmo que haja apenas um produto ou serviço, o campo "Produtos" deve estar presente e preenchido no JSON de resposta.

- Retorne as datas sempre no formato dd/mm/aaaa.
- O campo Prazo deve ser a diferença em dias entre data de vencimento e data de emissão (em dias corridos, pode ser negativo se vencimento for antes da emissão).
- Não inclua os campos Cnpj_Fornecedor_Trecho e Cnpj_Cliente_Trecho no JSON de resposta.
- Responda apenas com o JSON, sem explicações, sem comentários, sem texto antes ou depois. Não inclua nada além do JSON.

Notas fiscais:
'''

EXEMPLO_JSON = r'''Responda em JSON, exemplo:
[
  {
    "Arquivo": "...",
    "Numero_Nota": "...",
    "Cnpj_Fornecedor": "...",
    "Cnpj_Cliente": "...",
    "Data_Emissao": "...",
    "Data_Vencimento": "...",
    "Condição_de_Pagamento": "...",
    "Prazo": "...",
    "Valor_Total": "...",
    "Contrato_de_Parceria": "SIM ou NÃO",
    "Produtos": [
      {
        "Produto": "...",
        "Qtde": "...",
        "Valor_Unitario": "...",
        "Valor_Total_Produto": "..."
      }
    ]
  }
]
'''

def limpar_json_bruto(resposta):
    # Remove blocos de markdown e espaços extras
    resposta = resposta.strip()
    # Remove blocos ```json ... ``` ou ``` ... ```
    resposta = re.sub(r'```json|```', '', resposta, flags=re.IGNORECASE).strip()
    # Remove comentários de linha (// ...)
    resposta = re.sub(r'//.*', '', resposta)
    # Remove vírgulas finais antes de fechar colchetes/chaves
    resposta = re.sub(r',([ \t\r\n]*[\]\}])', r'\1', resposta)
    # Corrige aspas simples para duplas em todo o texto
    resposta = resposta.replace("'", '"')
    # Remove espaços extras no início/fim
    return resposta

def tabular_nota(nota, arquivo):
    prompt = PROMPT_BASE
    prompt += f"\nArquivo: {arquivo}\nTexto:\n{nota.get('texto_lido', '')}\n"
    prompt += EXEMPLO_JSON
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Você é um extrator de informações fiscais que responde apenas em JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
        max_tokens=1500
    )
    return response.choices[0].message.content

def corrigir_produtos_e_contrato(dado):
    # Garante que Produtos é uma lista
    produtos = dado.get('Produtos')
    if not isinstance(produtos, list):
        if produtos:
            produtos = [produtos]
        else:
            produtos = []
    dado['Produtos'] = produtos
    # Garante Contrato_de_Parceria
    if len(produtos) > 1:
        dado['Contrato_de_Parceria'] = 'SIM'
    else:
        dado['Contrato_de_Parceria'] = 'NÃO'
    return dado

def main():
    with open('resultado_notas.json', 'r', encoding='utf-8') as f:
        notas = json.load(f)
    resultados = []
    for idx, nota in enumerate(notas):
        arquivo = nota.get('arquivo', f'nota_{idx+1}')
        print(f"Processando {arquivo}...")
        try:
            resultado_bruto = tabular_nota(nota, arquivo)
            # Salva a resposta bruta em um arquivo de log
            with open('openai_respostas_brutas.log', 'a', encoding='utf-8') as flog:
                flog.write(f'Arquivo: {arquivo}\nResposta:\n{resultado_bruto}\n---\n')
            resultado_limpo = limpar_json_bruto(resultado_bruto)
            dado = json.loads(resultado_limpo)[0]
            dado = corrigir_produtos_e_contrato(dado)
            resultados.append(dado)
        except Exception as e:
            print(f"Erro ao processar {arquivo}: {e}")
            print(f"Resposta bruta da OpenAI:\n{resultado_bruto if 'resultado_bruto' in locals() else 'N/A'}")
            resultados.append({"Arquivo": arquivo, "erro": str(e)})
        time.sleep(1.5)  # Para evitar rate limit
    with open('resultado_notas_tabulado.json', 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print("Processamento concluído! Resultados salvos em 'resultado_notas_tabulado.json'.")

if __name__ == "__main__":
    main()

def processar_multas(files):
    aviso = "A conversão de imagem em texto pode demorar alguns minutos."
    if not files:
        return aviso, "Nenhum arquivo enviado."
    caminhos = []
    for f in files:
        # Se f já for um caminho, apenas adicione
        if isinstance(f, str):
            caminhos.append(f)
        else:
            # Se for NamedString ou similar, salve em temp e adicione o caminho
            temp_dir = "temp_multas"
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, os.path.basename(f.name))
            with open(temp_path, "wb") as out, open(f.name, "rb") as inp:
                out.write(inp.read())
            caminhos.append(temp_path)
    resultados = processar_multas_backend(caminhos)
    preview = []
    for r in resultados:
        preview.append(f"Arquivo: {r['arquivo_original']} | Placa: {r['placa']} | Auto: {r['auto_infracao']} | Data: {r['data_infracao']}")
    return aviso, "\n".join(preview) 