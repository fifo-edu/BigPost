import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import get_current_user, require_role
from app.models.models import BankConfig, BankEntry, BankImport, Charge, Licensee, Remittance, User
from app.schemas.schemas import BankConfigUpdate, BankImportRequest, BankReconcileRequest, RemittanceRequest
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/bank", tags=["bank"])


@router.get("/config")
def get_config(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.get(BankConfig, 1)


@router.put("/config")
def update_config(
    payload: BankConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    cfg = db.get(BankConfig, 1)
    before = {"cnab_layout": cfg.cnab_layout, "agreement": cfg.agreement}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cfg, field, value)
    cfg.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cfg)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ALTERAR_PARAMETROS_BB",
        entity="bank_config",
        before=before,
        after=payload.model_dump(exclude_unset=True),
        ip_address=client_ip(request),
    )
    return cfg


@router.get("/entries")
def list_entries(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(BankEntry).order_by(BankEntry.id.desc()).limit(500).all()


@router.post("/import")
def import_bank_file(
    payload: BankImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Operador")),
):
    text = payload.content
    if not text.strip():
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    rows: list[tuple] = []
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        for raw_row in reader:
            norm = {str(k or "").strip().lower(): str(v or "").strip() for k, v in raw_row.items()}

            def pick(*names):
                for name in names:
                    for k, v in norm.items():
                        if name in k:
                            return v
                return ""

            entry_date = pick("data", "date")
            document = pick("documento", "document", "id")
            payer = pick("pagador", "nome", "payer", "cliente")
            val = pick("valor", "amount", "credito", "crédito")
            try:
                amount = float(val.replace(".", "").replace(",", ".")) if "," in val else float(val)
            except ValueError:
                continue
            if amount > 0:
                rows.append((entry_date, document, payer, amount, raw_row))
    except Exception:
        raise HTTPException(
            status_code=400, detail="Não foi possível interpretar o arquivo. Envie CSV/TXT exportado pelo banco."
        )

    bank_import = BankImport(
        file_name=payload.file_name,
        imported_by=user.username,
        total_rows=len(rows),
        matched_rows=0,
        pending_rows=len(rows),
    )
    db.add(bank_import)
    db.flush()
    for entry_date, document, payer, amount, raw_row in rows:
        db.add(
            BankEntry(
                import_id=bank_import.id,
                entry_date=entry_date,
                document=document,
                payer=payer,
                amount=amount,
                raw_line=str(raw_row),
                status="Pendente",
            )
        )
    db.commit()
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="IMPORTAR_ARQUIVO_BB",
        entity=payload.file_name,
        after={"linhas": len(rows)},
        origin="Importação Bancária",
        ip_address=client_ip(request),
    )
    return {"ok": True, "rows": len(rows)}


@router.post("/reconcile")
def reconcile(
    payload: BankReconcileRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Operador")),
):
    entry = db.get(BankEntry, payload.entry_id)
    charge = db.get(Charge, payload.charge_id)
    if not entry or not charge:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    if abs(float(entry.amount) - float(charge.amount)) > 0.009:
        raise HTTPException(
            status_code=400, detail="Valor bancário diverge da cobrança. Conciliação manual exige valores iguais."
        )
    entry.status = "Conciliado"
    entry.charge_id = charge.id
    entry.matched_at = datetime.utcnow()
    entry.matched_by = user.username
    before_status = charge.status
    charge.status = "Paga"
    charge.paid_at = datetime.utcnow()
    db.commit()
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CONCILIAR_COBRANCA",
        entity=f"charge:{charge.id}",
        before={"status": before_status},
        after={"status": "Paga", "valor": float(entry.amount)},
        origin="Importação Bancária",
        details={"bank_entry_id": entry.id},
        ip_address=client_ip(request),
    )
    return {"ok": True}


@router.post("/remittance")
def generate_remittance(
    payload: RemittanceRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    cfg = db.get(BankConfig, 1)
    rows = (
        db.query(Charge, Licensee)
        .join(Licensee, Licensee.id == Charge.licensee_id)
        .filter(Charge.reference_month == payload.reference_month, Charge.status == "Aberta")
        .order_by(Charge.id)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=400, detail="Nenhuma cobrança aberta para esta competência")
    if not cfg.cnab_layout or cfg.cnab_layout == "A DEFINIR":
        raise HTTPException(
            status_code=400,
            detail="Defina e valide o layout CNAB do convênio bancário antes de gerar uma remessa real.",
        )

    # Segurança: não inventamos posições de CNAB. Só geramos uma PRÉ-REMESSA de
    # conferência até recebermos/validarmos o layout real do convênio.
    lines = ["ID;CNPJ_CPF;SACADO;VENCIMENTO;VALOR;REFERENCIA"]
    for charge, licensee in rows:
        lines.append(
            f"{charge.id};{licensee.tax_id};{licensee.legal_name};{charge.due_date};{float(charge.amount):.2f};{charge.reference_month}"
        )
    content = "\n".join(lines)
    file_name = f"PRE_REMESSA_{payload.reference_month.replace('-', '')}.csv"
    total_amount = sum(float(c.amount) for c, _ in rows)

    remittance = Remittance(
        reference_month=payload.reference_month,
        due_date=rows[0][0].due_date,
        layout=cfg.cnab_layout,
        file_name=file_name,
        total_titles=len(rows),
        total_amount=total_amount,
        status="Pré-remessa - validar CNAB",
        created_by=user.username,
        content=content,
    )
    db.add(remittance)
    db.commit()
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="GERAR_PRE_REMESSA",
        entity=payload.reference_month,
        after={"titulos": len(rows), "arquivo": file_name},
        origin="Banco",
        ip_address=client_ip(request),
    )
    return {
        "ok": True,
        "file_name": file_name,
        "content": content,
        "warning": "Pré-remessa gerada. Não enviar ao banco até validarmos o layout CNAB real do convênio.",
    }


@router.get("/remittances")
def list_remittances(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Remittance).order_by(Remittance.id.desc()).limit(100).all()
