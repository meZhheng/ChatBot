from fastapi import Request


def get_rag_service(request: Request):
    return request.app.state.rag_service


def get_agent_service(request: Request):
    return request.app.state.agent_service


def get_wecom_client(request: Request):
    return request.app.state.wecom_client
