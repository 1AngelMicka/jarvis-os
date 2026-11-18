// Lecture d'un flux SSE reçu par fetch (POST : EventSource ne sait faire que GET).

export interface EvenementSSE {
  evenement: string;
  donnees: string;
}

/** Découpe les morceaux reçus en événements complets ; garde la fin incomplète pour le morceau suivant. */
export class LecteurSSE {
  private tampon = "";

  pousser(morceau: string): EvenementSSE[] {
    this.tampon += morceau.replace(/\r\n/g, "\n");
    const evenements: EvenementSSE[] = [];
    let fin = this.tampon.indexOf("\n\n");
    while (fin !== -1) {
      const bloc = this.tampon.slice(0, fin);
      this.tampon = this.tampon.slice(fin + 2);
      const ev = analyserBloc(bloc);
      if (ev) evenements.push(ev);
      fin = this.tampon.indexOf("\n\n");
    }
    return evenements;
  }
}

function analyserBloc(bloc: string): EvenementSSE | null {
  let evenement = "message";
  const donnees: string[] = [];
  for (const ligne of bloc.split("\n")) {
    if (ligne.startsWith(":")) continue; // commentaire / battement
    const deuxPoints = ligne.indexOf(":");
    const champ = deuxPoints === -1 ? ligne : ligne.slice(0, deuxPoints);
    let valeur = deuxPoints === -1 ? "" : ligne.slice(deuxPoints + 1);
    if (valeur.startsWith(" ")) valeur = valeur.slice(1);
    if (champ === "event") evenement = valeur;
    else if (champ === "data") donnees.push(valeur);
  }
  return donnees.length ? { evenement, donnees: donnees.join("\n") } : null;
}
