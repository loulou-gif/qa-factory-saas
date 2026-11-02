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
            phrase.textContent = 'Génération terminée';
            if (aide) aide.textContent = 'Ouverture de vos fichiers…';
            setTimeout(fini, 1600);
          }, 700);
          return;
        }
        if (!d.actif) {
          zone.classList.remove('travail'); zone.classList.add('echec');
          phrase.textContent = "La génération n'a pas abouti";
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
  function squash(cadre) {
    var projet = cadre.getAttribute('data-projet');
    var saisie = cadre.querySelector('[data-zone=saisie]'), prog = cadre.querySelector('[data-zone=progression]');
    var phrase = prog.querySelector('.phrase-squash'), barre = prog.querySelector('.barre div');
    function montrer(texte, p) { saisie.hidden = true; prog.hidden = false; phrase.textContent = texte; barre.style.width = p + '%'; }
    function erreur(m) {
      prog.hidden = true; saisie.hidden = false;
      var ancien = cadre.querySelector('.message'); if (ancien) ancien.remove();
      cadre.insertBefore(el('div', { 'class': 'message erreur', texte: m }), cadre.firstChild);
      var b = saisie.querySelector('button'); if (b) b.disabled = false;
    }
    function suivre(tid, auFini) {
      api('/taches/' + tid + '/progression').then(function (d) {
        if (d.statut === 'termine') return auFini(d);
        if (!d.actif) return erreur(d.erreur || 'Échec.');
        montrer(d.message, d.pourcentage);
        setTimeout(function () { suivre(tid, auFini); }, 1200);
      }).catch(function (e) { erreur(e.message); });
    }
    cadre.querySelector('[data-action=verifier]').addEventListener('click', function (ev) {
      var champ = cadre.querySelector('#squash-id');
      ev.target.disabled = true;
      montrer('Vérification de ce qui existe déjà dans Squash', 8);
      api('/projets/' + projet + '/squash/simuler', { squash_id: champ ? champ.value.trim() : '' }).then(function (r) {
        suivre(r.tache, function (d) {
          var s = d.simulation || {}, res = s.resume || {}, n = (res.creer || 0) + (res.recreer || 0), pr = s.projet || {};
          montrer('Vérification terminée', 100);
          if (!n) { phrase.textContent = 'Tout est déjà dans Squash.'; return setTimeout(function () { location.reload(); }, 1200); }
          var minutes = Math.max(1, Math.ceil(n * 15 / 60));
          dialogue('Envoyer dans Squash ?', [
            el('p', { texte: n + ' éléments (exigences, cas de tests et dossiers) seront créés dans le projet Squash « ' + (pr.nom || '?') + ' » (n° ' + (pr.id || '?') + ').' }),
            el('p', { 'class': 'discret', texte: 'Rien de ce qui existe dans Squash ne sera modifié ni supprimé. Durée estimée : ' + minutes + ' min.' })
          ], [{ libelle: 'Annuler', valeur: false }, { libelle: 'Envoyer', valeur: true, principal: true }]).then(function (ok) {
            if (!ok) { prog.hidden = true; saisie.hidden = false; ev.target.disabled = false; return; }
            montrer('Envoi dans Squash', 3);
            api('/projets/' + projet + '/squash/publier', { simulation: r.tache }).then(function (p) {
              suivre(p.tache, function (f) {
                montrer('Envoyé dans Squash : ' + (f.crees || 0) + ' éléments créés', 100);
                setTimeout(function () { location.reload(); }, 1500);
              });
            }).catch(function (e) { erreur(e.message); });
          });
        });
      }).catch(function (e) { erreur(e.message); });
    });
  }

  window.QAF = { depot: depot, suivreTache: suivreTache, cas: cas, squash: squash };
})();
