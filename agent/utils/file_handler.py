import os
from agent.utils.logger_handler import logger
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, TextLoader

def get_file_md5_hex():
    pass

def listdir_with_allowed_type(path: str, allowed_type: tuple[str]):
    if not os.path.isdir(path):
        logger.error(f"{path}不是有效的文件路径")
        return allowed_type
    
    files = []
    for f in os.listdir(path):
        if f.endswith(allowed_type):
            files.append(os.path.join(path, f))
    
    return tuple(files)

def pdf_loader(filepath:str, passwd=None) -> list[Document]:
    return PyPDFLoader(filepath, passwd).load()

def txt_loader(filepath:str) -> list[Document]:
    return TextLoader(filepath).load()