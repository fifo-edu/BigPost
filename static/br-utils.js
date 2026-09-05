/* BigPost — utilitários de formatação/​integração para padrão brasileiro
 * (moeda, data, CPF/CNPJ, CEP) e autopreenchimento de endereço via CEP
 * (ViaCEP), compartilhado pelos 3 portais (Administração, Agência, Cliente).
 * Incluir com <script src="/br-utils.js"></script> antes do <script> inline
 * de cada página — funciona nos 3 porque cada mount estático (`/`, `/agencia`,
 * `/cliente`) resolve um caminho absoluto começando em "/" contra a raiz do
 * site, não contra o mount atual. */

function onlyDigits(s) {
  return (s || '').toString().replace(/\D/g, '');
}

function maskCEP(v) {
  const d = onlyDigits(v).slice(0, 8);
  return d.length > 5 ? d.slice(0, 5) + '-' + d.slice(5) : d;
}

function maskCPF(v) {
  const d = onlyDigits(v).slice(0, 11);
  if (d.length > 9) return d.slice(0, 3) + '.' + d.slice(3, 6) + '.' + d.slice(6, 9) + '-' + d.slice(9);
  if (d.length > 6) return d.slice(0, 3) + '.' + d.slice(3, 6) + '.' + d.slice(6);
  if (d.length > 3) return d.slice(0, 3) + '.' + d.slice(3);
  return d;
}

function maskCNPJ(v) {
  const d = onlyDigits(v).slice(0, 14);
  if (d.length > 12) return d.slice(0, 2) + '.' + d.slice(2, 5) + '.' + d.slice(5, 8) + '/' + d.slice(8, 12) + '-' + d.slice(12);
  if (d.length > 8) return d.slice(0, 2) + '.' + d.slice(2, 5) + '.' + d.slice(5, 8) + '/' + d.slice(8);
  if (d.length > 5) return d.slice(0, 2) + '.' + d.slice(2, 5) + '.' + d.slice(5);
  if (d.length > 2) return d.slice(0, 2) + '.' + d.slice(2);
  return d;
}

/* Campo único que aceita tanto CPF quanto CNPJ: decide o formato pela
 * quantidade de dígitos já digitados (>11 dígitos = CNPJ). */
function maskCpfCnpj(v) {
  const d = onlyDigits(v);
  return d.length > 11 ? maskCNPJ(v) : maskCPF(v);
}

/* Aplica uma função de máscara a um <input> conforme o usuário digita,
 * preservando a posição do cursor de forma simples (bom o suficiente para
 * campos numéricos curtos como CEP/CPF/CNPJ). */
function liveMask(input, maskFn) {
  if (!input) return;
  input.addEventListener('input', () => {
    const before = input.value;
    const posBefore = input.selectionStart ?? before.length;
    const digitsBefore = onlyDigits(before.slice(0, posBefore)).length;
    const masked = maskFn(before);
    input.value = masked;
    if (document.activeElement === input) {
      let pos = 0, digitsSeen = 0;
      while (pos < masked.length && digitsSeen < digitsBefore) {
        if (/\d/.test(masked[pos])) digitsSeen++;
        pos++;
      }
      try { input.setSelectionRange(pos, pos); } catch (e) {}
    }
  });
}

/* Moeda: número -> "R$ 1.234,56" */
function formatBRL(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return '';
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

/* "2026-09-04" ou ISO datetime -> "04/09/2026" */
function formatDateBR(isoStr) {
  if (!isoStr) return '';
  const m = String(isoStr).slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : String(isoStr);
}

/* ISO datetime -> "04/09/2026 14:32" */
function formatDateTimeBR(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (Number.isNaN(d.getTime())) return formatDateBR(isoStr);
  return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/* Busca um CEP no ViaCEP (mesma integração usada no módulo financeiro).
 * Retorna { street, district, city, state } ou null se não encontrado. */
async function lookupCEP(cep) {
  const d = onlyDigits(cep);
  if (d.length !== 8) return null;
  try {
    const res = await fetch(`https://viacep.com.br/ws/${d}/json/`);
    const data = await res.json();
    if (!res.ok || data.erro) return null;
    return { street: data.logradouro || '', district: data.bairro || '', city: data.localidade || '', state: data.uf || '' };
  } catch (e) {
    return null;
  }
}

/* Liga um campo de CEP a máscara automática + preenchimento de
 * Rua/Bairro/Cidade/UF assim que os 8 dígitos forem completados. Número e
 * Complemento nunca são tocados aqui — são sempre digitados manualmente.
 * targets: { street, district, city, state } — ids dos campos de destino
 * (qualquer um pode ser omitido se a tela não tiver aquele campo). */
function attachCepAutofill(cepId, targets) {
  const cepInput = document.getElementById(cepId);
  if (!cepInput) return;
  liveMask(cepInput, maskCEP);
  let lastLookedUp = '';
  const trigger = async () => {
    const d = onlyDigits(cepInput.value);
    if (d.length !== 8 || d === lastLookedUp) return;
    const addr = await lookupCEP(d);
    if (!addr) return;
    lastLookedUp = d;
    ['street', 'district', 'city', 'state'].forEach(key => {
      const id = targets[key];
      if (!id) return;
      const el = document.getElementById(id);
      if (el) el.value = addr[key];
    });
  };
  cepInput.addEventListener('blur', trigger);
  cepInput.addEventListener('input', () => { if (onlyDigits(cepInput.value).length === 8) trigger(); });
}

/* Comportamento padrão das telas de login dos 3 portais:
 * - Enter em qualquer campo (menos o de senha) avança para o próximo campo,
 *   na mesma ordem de `fieldIds` (Tab já faz isso nativamente, por estarem
 *   em ordem no HTML — aqui só cobrimos o Enter).
 * - Enter no campo de senha (o último de `fieldIds`) já dispara o login,
 *   sem precisar clicar em "Entrar".
 * - Acrescenta o botão "olho" dentro do campo de senha para mostrar/ocultar
 *   a senha digitada.
 * `fieldIds` na ordem de preenchimento (ex.: ['lu','lp'] ou ['lid','lu','lp']);
 * o último precisa ser o campo de senha. `onSubmit` é a função que realmente
 * faz a chamada de login (a mesma que já rodava no clique do botão). */
function setupLoginForm(fieldIds, onSubmit) {
  const fields = fieldIds.map((id) => document.getElementById(id)).filter(Boolean);
  if (!fields.length) return;
  const passwordField = fields[fields.length - 1];

  fields.forEach((field, i) => {
    field.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      if (field === passwordField) {
        onSubmit();
      } else {
        const next = fields[i + 1];
        if (next) next.focus();
      }
    });
  });

  if (passwordField && passwordField.type === 'password' && !passwordField.dataset.eyeAttached) {
    passwordField.dataset.eyeAttached = '1';
    const wrap = document.createElement('span');
    wrap.style.cssText = 'position:relative;display:inline-block';
    passwordField.parentNode.insertBefore(wrap, passwordField);
    wrap.appendChild(passwordField);
    passwordField.style.paddingRight = '30px';

    const eye = document.createElement('button');
    eye.type = 'button';
    eye.setAttribute('aria-label', 'Mostrar senha');
    eye.title = 'Mostrar/ocultar senha';
    eye.textContent = '👁';
    eye.style.cssText =
      'position:absolute;right:2px;top:50%;transform:translateY(-50%);border:none;background:none;' +
      'cursor:pointer;font-size:15px;line-height:1;padding:4px 6px;opacity:.7';
    eye.onclick = () => {
      const showing = passwordField.type === 'text';
      passwordField.type = showing ? 'password' : 'text';
      eye.textContent = showing ? '👁' : '🙈';
      passwordField.focus();
    };
    wrap.appendChild(eye);
  }
}
