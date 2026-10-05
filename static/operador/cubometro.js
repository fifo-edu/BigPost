// Leitura do cubômetro pela porta COM, direto do Chrome/Edge (Web Serial API —
// só funciona em HTTPS ou localhost, e o usuário escolhe a porta na primeira vez).
//
// O protocolo do aparelho ainda é desconhecido, então a leitura é genérica:
// pega a última linha recebida, extrai os números dela e usa a configuração
// (qual posição é comprimento, largura, altura e peso, e a unidade) salva
// neste navegador. A página "Cubômetro" do Operador mostra o que o aparelho
// manda, para descobrir essa configuração.
const Cubometro = (() => {
  const KEY = 'bigpost.cubometro';
  const DEFAULTS = {
    baudRate: 9600, dataBits: 8, parity: 'none', stopBits: 1,
    comando: '',            // enviado ao pedir leitura (ex.: \r, \x05); vazio = só escuta
    idxC: 0, idxL: 1, idxA: 2, idxP: 3, // posição de cada valor na linha (-1 = não vem)
    divDim: 1,              // 1 = cm, 10 = mm
    divPeso: 1,             // 1 = kg, 1000 = g
  };
  let port = null, reader = null, pipeFechado = null, buffer = '', flushTimer = null;
  const listeners = new Set();

  const suportado = () => 'serial' in navigator;

  function config() {
    try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch (e) { return { ...DEFAULTS }; }
  }
  function salvarConfig(cfg) {
    try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (e) {}
  }

  function numeros(linha) {
    return (linha.match(/\d+(?:[.,]\d+)?/g) || []).map(n => parseFloat(n.replace(',', '.')));
  }

  // Converte uma linha do aparelho em medidas, conforme a configuração.
  function interpretar(linha, cfg = config()) {
    const n = numeros(linha);
    const pega = (i, div) => (i >= 0 && i < n.length ? +(n[i] / div).toFixed(3) : null);
    return {
      numeros: n,
      c: pega(cfg.idxC, cfg.divDim), l: pega(cfg.idxL, cfg.divDim), a: pega(cfg.idxA, cfg.divDim),
      peso: pega(cfg.idxP, cfg.divPeso),
    };
  }

  function emitir(linha) {
    linha = linha.trim();
    if (linha) listeners.forEach(fn => fn(linha));
  }

  function receber(texto) {
    buffer += texto;
    const partes = buffer.split(/\r\n|\r|\n/);
    buffer = partes.pop();
    partes.forEach(emitir);
    // Aparelho que não termina a linha: considera a leitura completa após 300 ms parado.
    clearTimeout(flushTimer);
    flushTimer = setTimeout(() => { const b = buffer; buffer = ''; emitir(b); }, 300);
  }

  async function lerSempre() {
    const decoder = new TextDecoderStream('latin1');
    pipeFechado = port.readable.pipeTo(decoder.writable).catch(() => {});
    reader = decoder.readable.getReader();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) receber(value);
      }
    } catch (e) {
      // porta desconectada
    } finally {
      reader.releaseLock();
    }
  }

  async function conectar({ escolher = false } = {}) {
    if (!suportado()) throw new Error('Este navegador não acessa porta COM. Use o Chrome ou o Edge.');
    if (port) return port;
    const cfg = config();
    let p = escolher ? null : (await navigator.serial.getPorts())[0];
    if (!p) p = await navigator.serial.requestPort();
    await p.open({ baudRate: +cfg.baudRate, dataBits: +cfg.dataBits, parity: cfg.parity, stopBits: +cfg.stopBits });
    port = p;
    lerSempre();
    return port;
  }

  async function desconectar() {
    if (!port) return;
    // Ordem exigida pela Web Serial: cancela a leitura, espera o pipe soltar a porta, fecha.
    try { await reader?.cancel(); } catch (e) {}
    await pipeFechado;
    try { await port.close(); } catch (e) {}
    port = null;
  }

  // "\r", "\n", "\x05" viram os bytes correspondentes.
  function bytesDoComando(cmd) {
    const s = cmd.replace(/\\r/g, '\r').replace(/\\n/g, '\n').replace(/\\x([0-9a-fA-F]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
    return Uint8Array.from(s, ch => ch.charCodeAt(0) & 0xff);
  }

  async function enviarComando() {
    const cmd = config().comando;
    if (!port || !cmd) return;
    const w = port.writable.getWriter();
    try { await w.write(bytesDoComando(cmd)); } finally { w.releaseLock(); }
  }

  // Pede uma leitura e espera a próxima linha do aparelho.
  async function lerMedidas(timeoutMs = 8000) {
    await conectar();
    const linha = await new Promise((resolve, reject) => {
      const t = setTimeout(() => { listeners.delete(fn); reject(new Error('O cubômetro não enviou nenhuma leitura. Acione a medição no aparelho e tente de novo.')); }, timeoutMs);
      const fn = (l) => { clearTimeout(t); listeners.delete(fn); resolve(l); };
      listeners.add(fn);
      enviarComando().catch(() => {});
    });
    return { linha, ...interpretar(linha) };
  }

  return {
    suportado, config, salvarConfig, interpretar, conectar, desconectar, lerMedidas,
    conectado: () => !!port,
    onLinha: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  };
})();
