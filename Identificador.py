import os
import xmltodict
import re
import json
from tkinter import Tk, filedialog
from PyPDF2 import PdfReader
import cv2
from PIL import Image
import pytesseract
import easyocr
from tqdm import tqdm
from pdf2image import convert_from_path

# Função para o usuário escolher arquivos (um ou vários)
def selecionar_arquivos():
    Tk().withdraw()
    arquivos = filedialog.askopenfilenames(title="Selecione os arquivos das notas fiscais",
                                           filetypes=[("Todos os arquivos", "*.*"),
                                                      ("PDFs", "*.pdf"),
                                                      ("Imagens", "*.jpg;*.jpeg;*.png;*.bmp;*.tiff"),
                                                      ("XML", "*.xml")])
    if not arquivos:
        print("Nenhum arquivo selecionado. Encerrando o programa.")
        exit()
    return list(arquivos)

# Identificação do tipo de nota
def identificar_tipo_nota(caminho_arquivo):
    extensao = os.path.splitext(caminho_arquivo)[1].lower()
    if extensao == '.xml':
        return 'xml'
    elif extensao == '.pdf':
        try:
            reader = PdfReader(caminho_arquivo)
            for page in reader.pages:
                if page.extract_text():
                    return 'pdf_text'
            return 'pdf_image'
        except Exception:
            return 'unknown'
    elif extensao in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']:
        try:
            with Image.open(caminho_arquivo) as img:
                img.verify()  # Verifica se é uma imagem válida
            return 'image'
        except Exception:
            return 'unknown'
    else:
        return 'unknown'

# OCR com pytesseract
def ocr_pytesseract(image_path):
    try:
        img = Image.open(image_path)
        texto = pytesseract.image_to_string(img, lang='por')
        return texto
    except Exception as e:
        return ''

# OCR com easyocr
def ocr_easyocr(image_path):
    try:
        reader = easyocr.Reader(['pt'])
        resultado = reader.readtext(image_path, detail=0, paragraph=True)
        texto = '\n'.join(resultado)
        return texto
    except Exception as e:
        return ''

# Agentes de extração
def extrair_dados_xml(caminho_arquivo):
    with open(caminho_arquivo, 'rb') as f:
        xml_content = f.read()
        doc = xmltodict.parse(xml_content)
    try:
        infNFe = doc['Nfe']['infNFe']
        return {'texto_lido': xml_content.decode('utf-8', errors='ignore')}
    except Exception as e:
        return {'erro': str(e), 'texto_lido': xml_content.decode('utf-8', errors='ignore')}

def extrair_dados_pdf_texto(caminho_arquivo):
    reader = PdfReader(caminho_arquivo)
    texto = ""
    for page in reader.pages:
        texto += page.extract_text() or ""
    return {
        'texto_lido': texto
    }

def pdf_para_imagens(caminho_arquivo):
    # Converte cada página do PDF em imagem (usa Pillow e PyPDF2)
    reader = PdfReader(caminho_arquivo)
    imagens = []
    for i, page in enumerate(reader.pages):
        if '/XObject' in page['/Resources']:
            continue  # Ignora PDFs que já são pesquisáveis
        # Caso precise converter PDF para imagem, utilize bibliotecas como pdf2image
        # Aqui, apenas retorna o PDF, pois o pytesseract pode aceitar PDF diretamente
    return [caminho_arquivo]

def extrair_dados_imagem(caminho_arquivo):
    texto = ocr_easyocr(caminho_arquivo)
    return {
        'texto_lido': texto
    }

def extrair_dados_pdf_imagem(caminho_arquivo):
    textos = []
    try:
        paginas = convert_from_path(
            caminho_arquivo,
            poppler_path=r'C:\Users\paulo.lima.LUFT11\Desktop\ROBOS\poppler-24.08.0\Library\bin'
        )
        reader = easyocr.Reader(['pt'])
        for pagina in paginas:
            pagina.save('temp_page.png')
            texto = reader.readtext('temp_page.png', detail=0, paragraph=True)
            textos.append('\n'.join(texto))
        texto_total = '\n'.join(textos)
    except Exception as e:
        texto_total = ''
    return {
        'texto_lido': texto_total
    }

# Função principal para processar os arquivos
def processar_notas(arquivos):
    resultados = []
    for arquivo in tqdm(arquivos, desc='Processando notas', unit='nota'):
        tipo = identificar_tipo_nota(arquivo)
        if tipo == 'xml':
            dados = extrair_dados_xml(arquivo)
        elif tipo == 'pdf_text':
            dados = extrair_dados_pdf_texto(arquivo)
        elif tipo == 'pdf_image':
            dados = extrair_dados_pdf_imagem(arquivo)
        elif tipo == 'image':
            dados = extrair_dados_imagem(arquivo)
        else:
            dados = {'tipo': 'unknown', 'arquivo': arquivo}
        # Adiciona o nome do arquivo ao resultado
        dados['arquivo'] = os.path.basename(arquivo)
        resultados.append(dados)
    return resultados

# Função principal para processar um arquivo individual (para integração com Flask)
def processar_arquivo_identificador(path):
    tipo = identificar_tipo_nota(path)
    if tipo == 'xml':
        dados = extrair_dados_xml(path)
    elif tipo == 'pdf_text':
        dados = extrair_dados_pdf_texto(path)
    elif tipo == 'pdf_image':
        dados = extrair_dados_pdf_imagem(path)
    elif tipo == 'image':
        dados = extrair_dados_imagem(path)
    else:
        dados = {'tipo': 'unknown', 'arquivo': os.path.basename(path)}
    dados['arquivo'] = os.path.basename(path)
    return dados

# Programa principal
if __name__ == "__main__":
    arquivos_notas = selecionar_arquivos()
    print(f"Arquivos selecionados: {arquivos_notas}")
    resultados = processar_notas(arquivos_notas)
    json_final = json.dumps(resultados, indent=2, ensure_ascii=False)
    print(json_final)
    # Salvar o JSON em arquivo
    with open("resultado_notas.json", "w", encoding="utf-8") as f:
        f.write(json_final)
    print("Processamento concluído! Resultados salvos em 'resultado_notas.json'.")
