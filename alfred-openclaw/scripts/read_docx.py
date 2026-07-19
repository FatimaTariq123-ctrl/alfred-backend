import zipfile
import xml.etree.ElementTree as ET
import sys

def extract_text_from_docx(docx_path):
    try:
        document = zipfile.ZipFile(docx_path)
        xml_content = document.read('word/document.xml')
        document.close()
        tree = ET.XML(xml_content)
        
        namespace = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs = tree.findall('.//w:p', namespace)
        
        text = []
        for paragraph in paragraphs:
            texts = [node.text for node in paragraph.findall('.//w:t', namespace) if node.text]
            if texts:
                text.append(''.join(texts))
        
        return '\n'.join(text)
    except Exception as e:
        return f"Error extracting text: {e}"

if __name__ == '__main__':
    if len(sys.argv) > 1:
        print(extract_text_from_docx(sys.argv[1]))
