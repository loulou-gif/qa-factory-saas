/* QA Factory — comportements de l'interface (sans dépendance). */
(function () {
  'use strict';
  var csrf = (document.querySelector('meta[name=csrf]') || {}).content || '';

  function api(url, corps) {
    return fetch(url, {
      method: corps === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: Object.assign({ 'Accept': 'application/json', 'X-CSRF': csrf }, corps === undefined ? {} : { 'Content-Type': 'application/json' }),
      body: corps === undefined ? undefined : JSON.stringify(corps)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) { var e = new Error(d.erreur || ('Erreur ' + r.status)); e.details = d.details; e.statut = r.status; throw e; }
        return d;
      });
    });
  }

  function el(tag, attrs, enfants) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'texte') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (enfants || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }

  /* ---------- fenêtre de dialogue ---------- */
  function dialogue(titre, contenus, boutons) {
    return new Promise(function (resoudre) {
      var actions = el('div', { 'class': 'actions' });
      var boite = el('div', { 'class': 'dialogue', role: 'dialog', 'aria-modal': 'true', 'aria-label': titre }, [el('h2', { texte: titre })].concat(contenus).concat([actions]));
      var voile = el('div', { 'class': 'voile' }, [boite]);
      function fermer(v) { voile.remove(); resoudre(v); }
      boutons.forEach(function (b) {
        var bt = el('button', { type: 'button', 'class': 'bouton' + (b.principal ? '' : ' discret-btn'), texte: b.libelle });
        bt.addEventListener('click', function () { fermer(b.valeur); });
        actions.appendChild(bt);
      });
      voile.addEventListener('keydown', function (e) { if (e.key === 'Escape') fermer(null); });
      document.body.appendChild(voile);
      var p = actions.querySelector('.bouton:not(.discret-btn)') || actions.querySelector('button');
      if (p) p.focus();
    });
  }

  /* ---------- demandes de l'assistant pendant une tâche ---------- */
  var dejaVues = {};
  function traiterAttente(tid, attente) {
    attente.forEach(function (a) {
      if (dejaVues[a.id]) return;
      dejaVues[a.id] = true;
      if (a.genre === 'permission') {
        dialogue("L'assistant demande votre accord", [
          el('p', { texte: 'Pour continuer, il veut exécuter cette action :' }),
          el('pre', { texte: a.detail || a.permission }),
          el('p', { 'class': 'discret petit', texte: "Autorisez seulement si l'action sert la tâche et ne présente pas de risque. Les suppressions et les écritures dans Squash lui sont toujours interdites." })
        ], [{ libelle: 'Refuser', valeur: false }, { libelle: 'Autoriser', valeur: true, principal: true }]).then(function (ok) {
          api('/taches/' + tid + '/permission', { demande: a.id, accepter: !!ok }).catch(function () { dejaVues[a.id] = false; });
        });
      } else if (a.genre === 'question') {
        var q = (a.questions || [])[0] || {};
        var boutons = (q.options || []).map(function (o) { return { libelle: o.label, valeur: o.label, principal: false }; });
        boutons.push({ libelle: 'Ne pas répondre', valeur: null });
        dialogue(q.header || "L'assistant pose une question", [el('p', { texte: q.question || '' })], boutons).then(function (choix) {
          api('/taches/' + tid + '/question', choix ? { demande: a.id, reponses: [[choix]] } : { demande: a.id, ignorer: true });
        });
      }
    });
  }

  /* ---------- progression animée dans la zone (accueil et page projet) ---------- */
  function suivreTache(zone, tid, fini) {
    var remplissage = zone.querySelector('.remplissage'), pct = zone.querySelector('.pourcentage'),
        phrase = zone.querySelector('.phrase'), aide = zone.querySelector('.aide');
    var affiche = parseFloat(zone.getAttribute('data-affiche') || '0'), cible = affiche, termine = false;
    zone.classList.add('travail');
    function dessiner() {
      affiche += (cible - affiche) * 0.06;
      if (Math.abs(cible - affiche) < 0.05) affiche = cible;
      remplissage.style.width = affiche + '%';
      pct.textContent = Math.floor(affiche) + ' %';
      if (!termine || affiche < 100) requestAnimationFrame(dessiner);
    }
    remplissage.style.transition = 'none';
    requestAnimationFrame(dessiner);
    function interroger() {
      api('/taches/' + tid + '/progression').then(function (d) {
        if (d.statut === 'termine') {
          cible = 100; termine = true;
          setTimeout(function () {
            zone.classList.add('fini');
            phrase.textContent = d.type === 'tester' ? 'Tests terminés' : 'Génération terminée';
            if (aide) aide.textContent = d.type === 'tester' ? 'Ouverture des résultats…' : 'Ouverture de vos fichiers…';
            setTimeout(fini, 1600);
          }, 700);
          return;
        }
        if (!d.actif) {
          zone.classList.remove('travail'); zone.classList.add('echec');
          phrase.textContent = d.type === 'tester' ? "Les tests n'ont pas abouti" : "La génération n'a pas abouti";
          if (aide) aide.textContent = d.erreur || '';
          zone.dispatchEvent(new CustomEvent('echec'));
          return;
        }
        cible = Math.max(cible, d.pourcentage);
        phrase.textContent = d.message;
        traiterAttente(tid, d.attente || []);
        setTimeout(interroger, 1500);
      }).catch(function () { setTimeout(interroger, 4000); });
    }
    interroger();
  }

  /* ---------- accueil : déposer, c'est lancer ---------- */
  function depot(zone) {
    if (!zone || zone.getAttribute('aria-disabled') === 'true') return;
    var choix = document.getElementById('choix'), phrase = zone.querySelector('.phrase'), aide = zone.querySelector('.aide');
    var panier = document.getElementById('panier'), listeEl = panier.querySelector('ul'), lancer = document.getElementById('lancer');
    var exts = zone.getAttribute('data-extensions').split(','), occupe = false, selection = [];
    var texteInitial = [phrase.textContent, aide.textContent];
    function taille(o) { return o < 1048576 ? Math.max(1, Math.round(o / 1024)) + ' Ko' : (o / 1048576).toFixed(1).replace('.', ',') + ' Mo'; }
    function afficherPanier() {
      listeEl.innerHTML = '';
      selection.forEach(function (f, i) {
        var croix = el('button', { type: 'button', 'class': 'croix', 'aria-label': 'Retirer ' + f.name, texte: '\u00d7' });
        croix.addEventListener('click', function () { selection.splice(i, 1); afficherPanier(); });
        listeEl.appendChild(el('li', {}, [el('span', { 'class': 'nom', texte: f.name }), el('span', { 'class': 'discret', texte: taille(f.size) }), croix]));
      });
      panier.hidden = !selection.length;
      if (selection.length) {
        phrase.textContent = selection.length > 1 ? selection.length + ' documents prêts' : '1 document prêt';
        aide.textContent = "Ajoutez d'autres fichiers en cliquant ou en les déposant ici, puis lancez l'analyse.";
      } else {
        phrase.textContent = texteInitial[0]; aide.textContent = texteInitial[1];
      }
    }
    function reinitialiser() {
      occupe = false; selection = []; zone.className = 'depot'; zone.querySelector('.remplissage').style.width = '0';
      zone.setAttribute('data-affiche', '0'); afficherPanier();
    }
    function ajouter(fichiers) {
      if (occupe) return;
      if (zone.classList.contains('echec')) reinitialiser();
      var liste = Array.prototype.slice.call(fichiers);
      var refus = liste.filter(function (f) { return exts.indexOf(f.name.split('.').pop().toLowerCase()) < 0; });
      if (refus.length) { erreur(refus[0].name + ' : format non accepté.'); occupe = false; return; }
      liste.forEach(function (f) {
        if (!selection.some(function (s) { return s.name === f.name && s.size === f.size; })) selection.push(f);
      });
      afficherPanier();
      lancer.focus();
    }
    zone.addEventListener('click', function () { if (!occupe) choix.click(); });
    zone.addEventListener('keydown', function (e) { if ((e.key === 'Enter' || e.key === ' ') && !occupe) { e.preventDefault(); choix.click(); } });
    ['dragenter', 'dragover'].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); if (!occupe) zone.classList.add('survol'); }); });
    ['dragleave', 'drop'].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.remove('survol'); }); });
    zone.addEventListener('drop', function (e) { ajouter(e.dataTransfer.files); });
    choix.addEventListener('change', function () { if (choix.files.length) ajouter(choix.files); choix.value = ''; });
    lancer.addEventListener('click', function () { if (!occupe && selection.length) envoyer(selection); });

    function erreur(m) {
      zone.classList.remove('travail'); zone.classList.add('echec');
      phrase.textContent = 'Analyse impossible'; aide.textContent = m + ' Cliquez pour choisir d\'autres fichiers.';
      selection = []; panier.hidden = true;
    }
    function envoyer(liste) {
      occupe = true;
      panier.hidden = true;
      zone.classList.add('travail');
      phrase.textContent = liste.length > 1 ? 'Envoi de ' + liste.length + ' fichiers' : 'Envoi de ' + liste[0].name;
      aide.textContent = "L'analyse démarre dès la fin de l'envoi.";
      var donnees = new FormData();
      liste.forEach(function (f) { donnees.append('fichiers', f); });
      var x = new XMLHttpRequest();
      x.open('POST', '/demarrer');
      x.setRequestHeader('X-CSRF', csrf);
      x.setRequestHeader('Accept', 'application/json');
      var rempl = zone.querySelector('.remplissage'), pct = zone.querySelector('.pourcentage');
      x.upload.onprogress = function (e) {
        if (e.lengthComputable) { var p = 4 * e.loaded / e.total; rempl.style.width = p + '%'; pct.textContent = Math.floor(p) + ' %'; zone.setAttribute('data-affiche', p); }
      };
      x.onload = function () {
        var d = {}; try { d = JSON.parse(x.responseText); } catch (e) { /* réponse non JSON */ }
        if (x.status !== 200) { occupe = false; return erreur(d.erreur || ('Erreur ' + x.status + '.')); }
        aide.textContent = 'Projet « ' + d.nom + ' ». Vous pouvez quitter cette page : la génération continue.';
        suivreTache(zone, d.tache, function () { location.href = '/projets/' + d.projet; });
      };
      x.onerror = function () { occupe = false; erreur('Connexion au serveur perdue.'); };
      x.send(donnees);
    }
  }

  /* ---------- relecture des cas ---------- */
  function ajuster(t) { t.style.height = 'auto'; t.style.height = (t.scrollHeight + 2) + 'px'; }

  function cas(conteneur, modifiable) {
    if (!conteneur) return;
    var onglets = document.querySelectorAll('.onglets [role=tab]');
    onglets.forEach(function (o) {
      o.addEventListener('click', function () {
        onglets.forEach(function (x) { x.setAttribute('aria-selected', x === o ? 'true' : 'false'); });
        document.querySelectorAll('.groupe').forEach(function (g) { g.hidden = g.id !== o.getAttribute('aria-controls'); });
      });
    });
    conteneur.addEventListener('click', function (e) {
      var tete = e.target.closest('.cas-tete');
      if (tete) {
        var art = tete.closest('.cas'), ouvrir = !art.classList.contains('ouvert');
        art.classList.toggle('ouvert', ouvrir);
        tete.setAttribute('aria-expanded', ouvrir ? 'true' : 'false');
        if (ouvrir) art.querySelectorAll('textarea').forEach(ajuster);
        return;
      }
      var b = e.target.closest('[data-action]');
      if (!b || !modifiable) return;
      var article = b.closest('.cas'), corps = article.querySelector('.etapes tbody');
      if (b.getAttribute('data-action') === 'ajouter-etape') {
        var modele = corps.querySelector('tr');
        var neuf = modele.cloneNode(true);
        neuf.querySelectorAll('textarea').forEach(function (t) { t.value = ''; t.removeAttribute('data-origine'); });
        corps.appendChild(neuf);
        renumeroter(corps);
        neuf.querySelector('textarea').focus();
        marquer(article);
      } else if (b.getAttribute('data-action') === 'retirer-etape') {
        if (corps.querySelectorAll('tr').length <= 1) return;
        var tr = b.closest('tr');
        tr.style.transition = 'opacity .2s'; tr.style.opacity = '0';
        setTimeout(function () { tr.remove(); renumeroter(corps); marquer(article); }, 200);
      }
    });
    if (!modifiable) return;

    conteneur.querySelectorAll('textarea').forEach(function (t) { t.setAttribute('data-origine', t.value); });
    conteneur.addEventListener('input', function (e) {
      if (e.target.tagName !== 'TEXTAREA') return;
      ajuster(e.target);
      marquer(e.target.closest('.cas'));
    });
    function renumeroter(corps) {
      corps.querySelectorAll('tr').forEach(function (tr, i) { tr.querySelector('.n').textContent = i + 1; });
    }
    function lireEtapes(art) {
      return Array.prototype.map.call(art.querySelectorAll('.etapes tbody tr'), function (tr) {
        return { action: tr.querySelector('[data-champ=action]').value, resultat_attendu: tr.querySelector('[data-champ=resultat_attendu]').value };
      });
    }
    var origines = {};
    conteneur.querySelectorAll('.cas').forEach(function (a) { origines[a.getAttribute('data-id')] = JSON.stringify(lire(a)); });
    function lire(a) {
      var t = a.querySelector('[data-champ=titre]'), p = a.querySelector('[data-champ=prerequis]');
      return { id: a.getAttribute('data-id'), titre: t ? t.value : undefined, prerequis: p ? p.value : undefined, etapes: lireEtapes(a) };
    }
    var etat = document.getElementById('etat-modifs');
    function modifies() {
      return Array.prototype.filter.call(conteneur.querySelectorAll('.cas'), function (a) {
        return JSON.stringify(lire(a)) !== origines[a.getAttribute('data-id')];
      });
    }
    function marquer(art) {
      var change = JSON.stringify(lire(art)) !== origines[art.getAttribute('data-id')];
      art.classList.toggle('modifie', change);
      var titre = art.querySelector('[data-champ=titre]');
      if (titre) art.querySelector('.cas-tete .titre').textContent = titre.value || '(sans titre)';
      var n = modifies().length;
      etat.textContent = n ? n + ' cas modifié' + (n > 1 ? 's' : '') : 'Aucune modification';
      etat.classList.toggle('change', n > 0);
    }
    window.addEventListener('beforeunload', function (e) { if (modifies().length && !envoi) { e.preventDefault(); e.returnValue = ''; } });

    var envoi = false, bouton = document.getElementById('enregistrer');
    bouton.addEventListener('click', function () {
      var liste = modifies().map(lire);
      envoi = true; bouton.disabled = true; bouton.textContent = 'Enregistrement…';
      api('/projets/' + conteneur.getAttribute('data-projet') + '/enregistrer', { modifications: liste }).then(function (d) {
        bouton.textContent = 'Enregistré';
        etat.textContent = 'Validé';
        setTimeout(function () { location.href = d.redirection; }, 700);
      }).catch(function (e) {
        envoi = false; bouton.disabled = false; bouton.textContent = 'Enregistrer';
        var contenus = [el('p', { texte: e.message })];
        if (e.details && e.details.length) contenus.push(el('ul', {}, e.details.map(function (x) { return el('li', { texte: x }); })));
        dialogue('Enregistrement impossible', contenus, [{ libelle: 'Compris', valeur: true, principal: true }]);
      });
    });
  }

  /* ---------- envoi dans Squash ---------- */
  function sansAccents(t) { return String(t).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }

  /* Champ de recherche avec la liste des projets Squash (combobox ARIA) : on tape une partie du nom
     ou le numéro, on choisit au clavier ou à la souris ; le projet retenu est rappelé sous le champ. */
  function choixProjet(zone, projets) {
    var champ = zone.querySelector('#squash-recherche'), liste = zone.querySelector('#squash-liste');
    var cache = zone.querySelector('#squash-projet'), etat = zone.querySelector('.combo-etat');
    var ouvrir = zone.querySelector('.combo-ouvrir'), visibles = [], actif = -1, MAX = 60;
    function choisi() { return projets.filter(function (p) { return String(p.id) === cache.value; })[0]; }
    function afficherEtat() {
      var p = choisi();
      etat.textContent = '';
      zone.classList.toggle('combo-retenu', !!p);
      if (p) {
        etat.appendChild(document.createTextNode('Les cas seront envoyés dans '));
        etat.appendChild(el('strong', { texte: p.nom }));
        etat.appendChild(document.createTextNode(' (projet n° ' + p.id + ').'));
      } else {
        var n = projets.length;
        etat.textContent = n ? n + ' projet' + (n > 1 ? 's' : '') + ' visible' + (n > 1 ? 's' : '') + ' avec votre compte Squash.'
          : "Aucun projet visible avec ce compte Squash : vérifiez ses droits dans Squash.";
      }
    }
    function surligner(nom, t) {
      var span = el('span', { 'class': 'nom-projet' });
      var i = t ? sansAccents(nom).indexOf(t) : -1;
      if (i < 0) { span.textContent = nom; return span; }
      span.appendChild(document.createTextNode(nom.slice(0, i)));
      span.appendChild(el('mark', { texte: nom.slice(i, i + t.length) }));
      span.appendChild(document.createTextNode(nom.slice(i + t.length)));
      return span;
    }
    function fermer() { liste.hidden = true; champ.setAttribute('aria-expanded', 'false'); champ.removeAttribute('aria-activedescendant'); actif = -1; }
    function marquer(i) {
      var opts = liste.querySelectorAll('[role=option]');
      if (!opts.length) return;
      actif = (i + opts.length) % opts.length;
      opts.forEach(function (o, k) { o.classList.toggle('actif', k === actif); o.setAttribute('aria-selected', k === actif ? 'true' : 'false'); });
      champ.setAttribute('aria-activedescendant', opts[actif].id);
      opts[actif].scrollIntoView({ block: 'nearest' });
    }
    function prendre(p) {
      cache.value = String(p.id);
      champ.value = p.nom; fermer(); afficherEtat();
      var cadre = zone.closest('.encadre'), m = cadre && cadre.querySelector('.message.erreur');
      if (m) m.remove();
    }
    function remplir(tout) {
      var t = tout ? '' : sansAccents(champ.value.trim());
      visibles = projets.filter(function (p) { return !t || sansAccents(p.nom).indexOf(t) >= 0 || String(p.id) === t; });
      liste.innerHTML = '';
      if (!visibles.length) liste.appendChild(el('li', { 'class': 'combo-vide', texte: 'Aucun projet ne correspond à « ' + champ.value.trim() + ' ».' }));
      visibles.slice(0, MAX).forEach(function (p, k) {
        var li = el('li', { id: 'squash-option-' + k, role: 'option', 'aria-selected': 'false' },
          [surligner(p.nom, t), el('span', { 'class': 'numero-projet', texte: 'n° ' + p.id })]);
        if (String(p.id) === cache.value) li.classList.add('retenu');
        li.addEventListener('mousedown', function (e) { e.preventDefault(); prendre(p); });
        liste.appendChild(li);
      });
      if (visibles.length > MAX) liste.appendChild(el('li', { 'class': 'combo-vide', texte: (visibles.length - MAX) + ' autres projets : précisez la recherche.' }));
      liste.hidden = false; champ.setAttribute('aria-expanded', 'true'); actif = -1;
      if (t && visibles.length) marquer(0);
    }
    champ.disabled = false;
    champ.placeholder = 'Tapez le nom ou le numéro du projet';
    var deja = choisi();
    if (deja) champ.value = deja.nom; else cache.value = '';
    afficherEtat();
    champ.addEventListener('input', function () {
      var p = choisi();
      if (p && champ.value !== p.nom) { cache.value = ''; afficherEtat(); }
      remplir(false);
    });
    champ.addEventListener('focus', function () { remplir(!!choisi()); });
    champ.addEventListener('click', function () { if (liste.hidden) remplir(!!choisi()); });
    champ.addEventListener('blur', function () { fermer(); var p = choisi(); if (p) champ.value = p.nom; });
    champ.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (liste.hidden) remplir(!!choisi()); marquer(actif + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); if (liste.hidden) remplir(!!choisi()); marquer(actif - 1); }
      else if (e.key === 'Enter') { if (!liste.hidden && actif >= 0 && visibles[actif]) { e.preventDefault(); prendre(visibles[actif]); } }
      else if (e.key === 'Escape') { if (!liste.hidden) { e.preventDefault(); fermer(); } }
    });
    if (ouvrir) {
      ouvrir.disabled = false;
      ouvrir.addEventListener('mousedown', function (e) {
        e.preventDefault();
        if (liste.hidden) { champ.focus(); remplir(true); } else fermer();
      });
    }
    return { choisi: choisi };
  }

  function squash(cadre) {
    var projet = cadre.getAttribute('data-projet');
    var saisie = cadre.querySelector('[data-zone=saisie]'), prog = cadre.querySelector('[data-zone=progression]');
    var phrase = prog.querySelector('.phrase-squash'), barre = prog.querySelector('.barre div');
    var boutonArret = prog.querySelector('[data-action=arreter]');
    var zoneChoix = cadre.querySelector('#combo-squash'), selecteur = null, tacheEnCours = null;
    function montrer(texte, p) { saisie.hidden = true; prog.hidden = false; phrase.textContent = texte; barre.style.width = p + '%'; }
    function message(m, genre) {
      prog.hidden = true; saisie.hidden = false; boutonArret.hidden = true; tacheEnCours = null;
      var ancien = cadre.querySelector('.message'); if (ancien) ancien.remove();
      cadre.insertBefore(el('div', { 'class': 'message ' + genre, texte: m }), cadre.firstChild);
      var b = saisie.querySelector('[data-action=verifier]'); if (b) b.disabled = false;
    }
    function erreur(m) { message(m, 'erreur'); }
    if (zoneChoix) {
      api('/projets/' + projet + '/squash/projets').then(function (d) {
        selecteur = choixProjet(zoneChoix, d.projets || []);
      }).catch(function (e) {
        // Liste indisponible : on garde la saisie du numéro, comme avant.
        var cache = zoneChoix.querySelector('#squash-projet');
        var champ = el('input', { type: 'text', id: 'squash-numero', inputmode: 'numeric', placeholder: 'Numéro du projet Squash, ex. 28' });
        champ.value = cache.value;
        zoneChoix.querySelector('.combo-saisie').replaceWith(champ);
        zoneChoix.querySelector('.combo-etat').textContent = '';
        cadre.insertBefore(el('div', { 'class': 'message alerte', texte: 'Liste des projets Squash indisponible (' + e.message + ') : indiquez le numéro du projet.' }), cadre.firstChild);
      });
    }
    boutonArret.addEventListener('click', function () {
      if (!tacheEnCours) return;
      boutonArret.disabled = true; boutonArret.textContent = 'Arrêt en cours…';
      api('/taches/' + tacheEnCours + '/arreter', {}).catch(function (e) { boutonArret.disabled = false; boutonArret.textContent = "Arrêter l'envoi"; erreur(e.message); });
    });
    function suivre(tid, auFini, arretable) {
      tacheEnCours = tid;
      if (arretable && boutonArret.hidden) { boutonArret.hidden = false; boutonArret.disabled = false; boutonArret.textContent = "Arrêter l'envoi"; }
      api('/taches/' + tid + '/progression').then(function (d) {
        if (d.statut === 'termine') { boutonArret.hidden = true; tacheEnCours = null; return auFini(d); }
        if (d.statut === 'annule') return message(d.erreur || 'Envoi arrêté.', 'alerte');
        if (!d.actif) return erreur(d.erreur || 'Échec.');
        montrer(d.message, d.pourcentage);
        setTimeout(function () { suivre(tid, auFini, arretable); }, 1200);
      }).catch(function (e) { erreur(e.message); });
    }
    cadre.querySelector('[data-action=verifier]').addEventListener('click', function (ev) {
      var corps = { url: (cadre.querySelector('#squash-url') || {}).value || '' };
      var numero = cadre.querySelector('#squash-numero');
      if (numero) {
        corps.squash_id = numero.value.trim();
      } else if (zoneChoix) {
        var p = selecteur && selecteur.choisi();
        if (!p) {
          erreur(selecteur ? 'Choisissez le projet Squash dans la liste.' : 'La liste des projets Squash est en cours de chargement.');
          var r = cadre.querySelector('#squash-recherche'); if (r && !r.disabled) r.focus();
          return;
        }
        corps.squash_id = String(p.id); corps.squash_nom = p.nom;
      }
      ev.target.disabled = true;
      montrer('Vérification de ce qui existe déjà dans Squash', 8);
      api('/projets/' + projet + '/squash/simuler', corps).then(function (r) {
        suivre(r.tache, function (d) {
          var s = d.simulation || {}, res = s.resume || {}, n = (res.creer || 0) + (res.recreer || 0), pr = s.projet || {};
          var jeux = s.jeux || {}, nJeux = (jeux.a_creer || 0) + (jeux.a_completer || 0);
          montrer('Vérification terminée', 100);
          if (!n && !nJeux) { phrase.textContent = 'Tout est déjà dans Squash.'; return setTimeout(function () { location.reload(); }, 1200); }
          var minutes = Math.max(1, Math.ceil((n + nJeux) * 15 / 60));
          var lignes = [el('p', { texte: (n ? n + ' éléments (exigences, cas de tests et dossiers) seront créés' : 'Aucun nouveau cas à créer') + ' dans le projet Squash « ' + (pr.nom || '?') + ' ».' })];
          if (nJeux) lignes.push(el('p', { texte: nJeux + ' jeu' + (nJeux > 1 ? 'x' : '') + ' de données ' + (nJeux > 1 ? 'seront renseignés' : 'sera renseigné') + ' sur les cas.' }));
          if (s.exclus) lignes.push(el('p', { 'class': 'discret', texte: s.exclus + ' cas en attente d\'une réponse bloquante ne sont pas envoyés.' }));
          lignes.push(el('p', { 'class': 'discret', texte: 'Rien de ce qui existe dans Squash ne sera modifié ni supprimé. Durée estimée : ' + minutes + ' min. Vous pourrez arrêter l\'envoi en cours de route : une relance reprendra la suite, sans doublon.' }));
          dialogue('Envoyer dans Squash ?', lignes, [{ libelle: 'Annuler', valeur: false }, { libelle: 'Envoyer', valeur: true, principal: true }]).then(function (ok) {
            if (!ok) { prog.hidden = true; saisie.hidden = false; ev.target.disabled = false; return; }
            montrer('Envoi dans Squash', 3);
            api('/projets/' + projet + '/squash/publier', { simulation: r.tache }).then(function (p) {
              suivre(p.tache, function (f) {
                montrer('Envoyé dans Squash : ' + (f.crees || 0) + ' éléments créés', 100);
                setTimeout(function () { location.reload(); }, 1500);
              }, true);
            }).catch(function (e) { erreur(e.message); });
          });
        });
      }).catch(function (e) { erreur(e.message); });
    });
  }

  /* ---------- tests de l'application : lancement ---------- */
  function lancerTests(cadre) {
    if (!cadre) return;
    var bouton = cadre.querySelector('[data-action=tester]');
    if (!bouton) return;
    bouton.addEventListener('click', function () {
      var texte = bouton.textContent;
      bouton.disabled = true; bouton.textContent = 'Démarrage…';
      api('/projets/' + cadre.getAttribute('data-projet') + '/tester', {}).then(function () {
        location.reload();
      }).catch(function (e) {
        bouton.disabled = false; bouton.textContent = texte;
        var ancien = cadre.querySelector('.message'); if (ancien) ancien.remove();
        cadre.insertBefore(el('div', { 'class': 'message erreur', texte: e.message }), cadre.firstChild);
      });
    });
  }

  /* ---------- modifications de cas proposées après les tests ---------- */
  function modifications(zone) {
    if (!zone) return;
    var cases = zone.querySelectorAll('[data-garder]'), bouton = document.getElementById('appliquer');
    var compte = document.getElementById('compte-garder');
    function maj() {
      var n = 0;
      cases.forEach(function (c) { if (c.checked) n++; c.closest('.modif').classList.toggle('ecartee', !c.checked); });
      compte.textContent = n + ' sur ' + cases.length + ' correction' + (cases.length > 1 ? 's' : '') + ' gardée' + (n > 1 ? 's' : '');
      bouton.textContent = n ? 'Appliquer ' + n + ' correction' + (n > 1 ? 's' : '') : 'Tout refuser';
    }
    cases.forEach(function (c) { c.addEventListener('change', maj); });
    maj();
    bouton.addEventListener('click', function () {
      var acceptes = [];
      cases.forEach(function (c) { if (c.checked) acceptes.push(c.closest('.modif').getAttribute('data-id')); });
      var lignes = [el('p', { texte: acceptes.length
        ? acceptes.length + ' cas de la version validée seront modifiés (' + acceptes.join(', ') + '). Les autres propositions seront refusées.'
        : 'Toutes les propositions seront refusées ; les cas restent inchangés.' })];
      dialogue(acceptes.length ? 'Appliquer les corrections ?' : 'Tout refuser ?', lignes,
        [{ libelle: 'Annuler', valeur: false }, { libelle: acceptes.length ? 'Appliquer' : 'Tout refuser', valeur: true, principal: true }]).then(function (ok) {
        if (!ok) return;
        bouton.disabled = true;
        api('/projets/' + zone.getAttribute('data-projet') + '/tests/modifications', { campagne: zone.getAttribute('data-campagne'), acceptes: acceptes })
          .then(function (r) { location.href = r.redirection; })
          .catch(function (e) {
            bouton.disabled = false;
            dialogue('Modifications non appliquées', [el('p', { texte: e.message })], [{ libelle: 'Compris', valeur: true, principal: true }]);
          });
      });
    });
  }

  /* ---------- questions : réponses et faux positifs ---------- */
  function questions(conteneur) {
    if (!conteneur) return;
    var projet = conteneur.getAttribute('data-projet');
    conteneur.querySelectorAll('article[data-question]').forEach(function (carte) {
      var zone = carte.querySelector('.repondre'); if (!zone) return;
      var qid = carte.getAttribute('data-question'), texte = zone.querySelector('textarea');
      function envoyer(fauxPositif, bouton) {
        var ancien = carte.querySelector('.message'); if (ancien) ancien.remove();
        if (!fauxPositif && !texte.value.trim()) { texte.focus(); return; }
        bouton.disabled = true;
        api('/projets/' + projet + '/questions/' + qid, { reponse: texte.value, faux_positif: fauxPositif }).then(function (d) {
          var rep = carte.querySelector('.reponse');
          rep.querySelector('span').textContent = fauxPositif ? 'Sans objet (faux positif)' + (texte.value.trim() ? ' — ' + texte.value.trim() : '') : texte.value.trim();
          rep.hidden = false;
          var st = carte.querySelector('.statut'); st.textContent = d.statut.charAt(0).toUpperCase() + d.statut.slice(1); st.hidden = false;
          var bl = carte.querySelector('.bloque'); if (bl) bl.remove();
          zone.remove();
          var nb = document.getElementById('nb-ouvertes'); if (nb) nb.textContent = Math.max(0, parseInt(nb.textContent, 10) - 1);
          carte.classList.add('repondue');
        }).catch(function (e) {
          bouton.disabled = false;
          zone.appendChild(el('div', { 'class': 'message erreur', texte: e.message }));
        });
      }
      zone.querySelector('[data-action=repondre]').addEventListener('click', function (e) { envoyer(false, e.target); });
      zone.querySelector('[data-action=faux-positif]').addEventListener('click', function (e) { envoyer(true, e.target); });
    });
  }

  /* ---------- jeux de données : modification ---------- */
  function jeux(conteneur) {
    if (!conteneur) return;
    var projet = conteneur.getAttribute('data-projet'), bouton = document.getElementById('enregistrer-jeux'), etat = document.getElementById('etat-jeux');
    if (!bouton) return;
    var modifies = {};
    function marquer(carte) {
      modifies[carte.getAttribute('data-jeu')] = true;
      var n = Object.keys(modifies).length;
      etat.textContent = n + ' jeu' + (n > 1 ? 'x' : '') + ' modifié' + (n > 1 ? 's' : '');
      etat.classList.add('change');
    }
    function ligne() {
      var tr = el('tr', {}, [
        el('td', { 'data-libelle': 'Champ' }, [el('input', { type: 'text', 'data-champ': 'champ', 'aria-label': 'Champ' })]),
        el('td', { 'data-libelle': 'Valeur' }, [el('input', { type: 'text', 'data-champ': 'valeur', 'aria-label': 'Valeur' })]),
        el('td', { 'data-libelle': 'Remarque' }, [el('input', { type: 'text', 'data-champ': 'remarque', 'aria-label': 'Remarque' })]),
        el('td', { 'class': 'suppr' }, [el('button', { type: 'button', 'class': 'croix', 'data-action': 'retirer-ligne', 'aria-label': 'Retirer ce champ', texte: '×' })])
      ]);
      return tr;
    }
    conteneur.addEventListener('input', function (e) { var c = e.target.closest('article[data-jeu]'); if (c) marquer(c); });
    conteneur.addEventListener('click', function (e) {
      var b = e.target.closest('[data-action]'); if (!b) return;
      var carte = b.closest('article[data-jeu]');
      if (b.getAttribute('data-action') === 'retirer-ligne') { b.closest('tr').remove(); marquer(carte); }
      if (b.getAttribute('data-action') === 'ajouter-ligne') { var tr = ligne(); carte.querySelector('tbody').appendChild(tr); tr.querySelector('input').focus(); marquer(carte); }
    });
    bouton.addEventListener('click', function () {
      var ids = Object.keys(modifies);
      if (!ids.length) { etat.textContent = 'Aucune modification'; return; }
      var modifications = ids.map(function (id) {
        var carte = conteneur.querySelector('article[data-jeu="' + id + '"]');
        return { id: id, lignes: Array.prototype.map.call(carte.querySelectorAll('tbody tr'), function (tr) {
          var v = function (k) { var i = tr.querySelector('[data-champ=' + k + ']'); return i ? i.value : ''; };
          return { champ: v('champ'), valeur: v('valeur'), remarque: v('remarque') };
        }) };
      });
      bouton.disabled = true; etat.textContent = 'Enregistrement…';
      api('/projets/' + projet + '/donnees', { modifications: modifications }).then(function (d) {
        modifies = {}; bouton.disabled = false; etat.classList.remove('change');
        etat.textContent = 'Enregistré (' + d.n + ' jeu' + (d.n > 1 ? 'x' : '') + ')';
      }).catch(function (e) { bouton.disabled = false; etat.textContent = e.message; });
    });
    window.addEventListener('beforeunload', function (e) { if (Object.keys(modifies).length) { e.preventDefault(); e.returnValue = ''; } });
  }

  window.QAF = { depot: depot, suivreTache: suivreTache, cas: cas, squash: squash, questions: questions, jeux: jeux,
                 lancerTests: lancerTests, modifications: modifications };
})();
