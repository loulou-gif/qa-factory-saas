// Garde réseau du module Squash : n'autorise que des adresses publiques, au moment même de la connexion.
//
// L'application vérifie déjà l'adresse avant de lancer le module, mais un nom de domaine peut
// répondre une adresse publique à cette vérification puis une adresse interne à la connexion
// (« DNS rebinding »), et fetch suit les redirections. Ici, fetch est remplacé par une version
// qui :
//   - contrôle chaque adresse IP réellement utilisée pour se connecter (option lookup de node:http) ;
//   - refuse une IP littérale interne ;
//   - ne suit aucune redirection (l'API Squash n'en fait pas ; une redirection est renvoyée telle quelle).
// Activé par SQUASH_RESEAU_PUBLIC_SEUL=1 (posé par l'application quand QAF_SQUASH_RESEAU_PRIVE n'est pas actif).

import dns from 'node:dns';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';

const interdits = new net.BlockList();
for (const [a, n] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8], ['169.254.0.0', 16], ['172.16.0.0', 12],
  ['192.0.0.0', 24], ['192.0.2.0', 24], ['192.88.99.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15],
  ['198.51.100.0', 24], ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4],
]) interdits.addSubnet(a, n, 'ipv4');
for (const [a, n] of [
  ['::', 127], ['64:ff9b::', 96], ['64:ff9b:1::', 48], ['100::', 64], ['2001::', 23], ['2001:db8::', 32],
  ['2002::', 16], ['fc00::', 7], ['fe80::', 10], ['fec0::', 10], ['ff00::', 8],
]) interdits.addSubnet(a, n, 'ipv6');

export function adresseInterne(ip) {
  const brute = String(ip).split('%')[0];
  const v4 = brute.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/i);
  if (v4) return adresseInterne(v4[1]);
  const famille = net.isIP(brute);
  if (!famille) return true;
  return interdits.check(brute, famille === 4 ? 'ipv4' : 'ipv6');
}

class ErreurReseauInterne extends Error {
  constructor(hote) {
    super(`reseau-interne : « ${hote} » mène à un réseau interne, que le service ne contacte pas.`);
    this.code = 'ERESEAUINTERNE';
  }
}

function lookupPublic(hote, options, rappel) {
  dns.lookup(hote, { ...options, all: true }, (err, adresses) => {
    if (err) return rappel(err);
    const interne = adresses.find((a) => adresseInterne(a.address));
    if (interne) return rappel(new ErreurReseauInterne(hote));
    if (options && options.all) return rappel(null, adresses);
    rappel(null, adresses[0].address, adresses[0].family);
  });
}

async function fetchPublic(entree, init = {}) {
  const url = new URL(typeof entree === 'string' || entree instanceof URL ? entree : entree.url);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new TypeError(`protocole refusé : ${url.protocol}`);
  const hote = url.hostname.replace(/^\[|\]$/g, '');
  if (net.isIP(hote) && adresseInterne(hote)) throw new ErreurReseauInterne(hote);
  const corps = init.body == null ? null : Buffer.from(typeof init.body === 'string' ? init.body : await new Response(init.body).arrayBuffer());
  const entetes = Object.fromEntries(new Headers(init.headers || {}).entries());
  if (corps) entetes['content-length'] = String(corps.length);
  const module = url.protocol === 'https:' ? https : http;
  return new Promise((resoudre, rejeter) => {
    const req = module.request(url, { method: init.method || 'GET', headers: entetes, lookup: lookupPublic, signal: init.signal }, (res) => {
      const morceaux = [];
      res.on('data', (m) => morceaux.push(m));
      res.on('error', (e) => rejeter(new TypeError('fetch failed', { cause: e })));
      res.on('end', () => {
        const h = new Headers();
        for (const [k, v] of Object.entries(res.headers)) {
          if (Array.isArray(v)) v.forEach((x) => h.append(k, x));
          else if (v != null) h.set(k, String(v));
        }
        const sansCorps = [101, 204, 205, 304].includes(res.statusCode);
        resoudre(new Response(sansCorps ? null : Buffer.concat(morceaux), { status: res.statusCode, statusText: res.statusMessage || '', headers: h }));
      });
    });
    req.setTimeout(120000, () => req.destroy(new Error('timeout')));
    req.on('error', (e) => rejeter(e && e.code === 'ERESEAUINTERNE' ? e : new TypeError(`fetch failed (${(e && e.code) || e})`, { cause: e })));
    if (corps) req.write(corps);
    req.end();
  });
}

export function installerGardeReseau() {
  if (process.env.SQUASH_RESEAU_PUBLIC_SEUL === '1') globalThis.fetch = fetchPublic;
}
