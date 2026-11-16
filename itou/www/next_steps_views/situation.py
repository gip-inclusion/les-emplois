"""The situation sentence of the "Prochaines étapes" job seeker page.

A few plain sentences on where the person stands in their IAE journey: their last contract and their PASS IAE.
Same scopes as the job seeker's page: IAE actors see the PASS IAE, only some of them see contracts.
"""

from itou.approvals.enums import ApprovalStatus


def _fr(date):
    return f"{date:%d/%m/%Y}"


def _where(request, contract):
    if contract.company is None:
        return "en structure d’insertion"
    if request.from_employer and contract.company_id == request.current_organization.pk:
        return "chez vous"
    return f"chez {contract.company.display_name}"


def contract_sentence(request, contract):
    if contract is None:
        return "Aucun contrat en structure d’insertion connu."
    where = _where(request, contract)
    if not contract.has_ended:
        if contract.end_date:
            return f"En contrat {where} depuis le {_fr(contract.start_date)}, jusqu’au {_fr(contract.end_date)}."
        return f"En contrat {where} depuis le {_fr(contract.start_date)}."
    if contract.end_date:
        return f"Son contrat {where} est terminé depuis le {_fr(contract.end_date)}."
    return f"Son contrat {where} est terminé."


def approval_sentence(approval, contract):
    if approval is None:
        return "Aucun PASS IAE."
    match approval.state:
        case ApprovalStatus.SUSPENDED:
            suspension = approval.ongoing_suspension
            return (
                f"Son PASS IAE est suspendu depuis le {_fr(suspension.start_at)}, "
                f"jusqu’au {_fr(suspension.end_at)}, motif : {suspension.get_reason_display()}."
            )
        case ApprovalStatus.FUTURE:
            return f"Son PASS IAE commence le {_fr(approval.start_at)}."
        case ApprovalStatus.VALID:
            sentence = f"Son PASS IAE est valide jusqu’au {_fr(approval.end_at)}."
            if contract and contract.has_ended:
                sentence += " Ses jours continuent d’être décomptés tant qu’il n’est pas suspendu."
            return sentence
    sentence = f"Son PASS IAE a expiré le {_fr(approval.end_at)}."
    if approval.is_in_waiting_period:
        sentence += (
            f" Jusqu’au {_fr(approval.waiting_period_end)}, seul un prescripteur habilité peut valider "
            "à nouveau son éligibilité."
        )
    return sentence


def situation_sentences(request, approval, contract, can_view_contracts):
    if not request.from_iae_actor:
        return []
    sentences = [approval_sentence(approval, contract)]
    if can_view_contracts:
        sentences.insert(0, contract_sentence(request, contract))
    return sentences
