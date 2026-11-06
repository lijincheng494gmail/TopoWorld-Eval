"""Offline execution-audit adapter; never reads client session logs."""
RECORDED_AUDITS = {}
def audit_thread(thread_id, expected_model):
    import copy
    if thread_id not in RECORDED_AUDITS:
        raise ValueError("No preserved execution audit for replay slot")
    result=copy.deepcopy(RECORDED_AUDITS[thread_id])
    result["offline_audit_replay"]=True
    result["new_host_or_model_verification_performed"]=False
    return result
