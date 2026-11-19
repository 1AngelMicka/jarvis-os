import { useEffect, useRef, useState } from "react";

import { type ImageJointe, poidsLisible } from "../images";

export interface ImageAffichee {
  id: string;
  nom: string;
  dataUrl: string;
  poids?: number;
}

interface VignettesProps {
  images: ImageAffichee[];
  /** Zone de saisie : chaque vignette a son bouton « Retirer ». */
  surRetirer?: (id: string) => void;
  /** Nombre d'images en cours de préparation (vignettes d'attente). */
  enPreparation?: number;
  libelle: string;
  className?: string;
}

/** Miniatures des images jointes ; un clic agrandit (visionneuse), « × » retire (zone de saisie seulement). */
export function Vignettes({ images, surRetirer, enPreparation = 0, libelle, className }: VignettesProps) {
  const [ouverte, setOuverte] = useState<number | null>(null);
  if (!images.length && !enPreparation) return null;
  return (
    <>
      <ul className={["vignettes", className].filter(Boolean).join(" ")} aria-label={libelle}>
        {images.map((img, i) => (
          <li key={img.id} className="vignette">
            <button
              type="button"
              className="vignette-image"
              aria-label={`Agrandir l'image ${String(i + 1)} : ${img.nom}`}
              title={img.poids ? `${img.nom} · ${poidsLisible(img.poids)}` : img.nom}
              onClick={() => {
                setOuverte(i);
              }}
            >
              <img src={img.dataUrl} alt="" draggable={false} />
            </button>
            {surRetirer && (
              <button
                type="button"
                className="vignette-retirer"
                aria-label={`Retirer l'image ${String(i + 1)} : ${img.nom}`}
                title="Retirer"
                onClick={() => {
                  surRetirer(img.id);
                }}
              >
                <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M7 7l10 10M17 7L7 17" />
                </svg>
              </button>
            )}
          </li>
        ))}
        {Array.from({ length: enPreparation }, (_, i) => (
          <li key={`attente${String(i)}`} className="vignette vignette--attente" aria-label="Image en préparation">
            <span className="vignette-image" />
          </li>
        ))}
      </ul>
      {ouverte !== null && images[ouverte] && (
        <Visionneuse
          images={images}
          indice={ouverte}
          surChanger={setOuverte}
          surFermer={() => {
            setOuverte(null);
          }}
        />
      )}
    </>
  );
}

interface VisionneuseProps {
  images: ImageAffichee[];
  indice: number;
  surChanger: (indice: number) => void;
  surFermer: () => void;
}

/** Image agrandie, dans une fenêtre modale (focus piégé, Échap ferme, flèches pour passer d'une image à l'autre). */
export function Visionneuse({ images, indice, surChanger, surFermer }: VisionneuseProps) {
  const fenetre = useRef<HTMLDialogElement>(null);
  const image = images[indice];
  const plusieurs = images.length > 1;

  useEffect(() => {
    const d = fenetre.current;
    const avant = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (d && !d.open) d.showModal();
    return () => {
      d?.close();
      avant?.focus(); // le focus revient sur la miniature
    };
  }, []);

  if (!image) return null;
  const aller = (pas: number) => {
    surChanger((indice + pas + images.length) % images.length);
  };

  return (
    <dialog
      ref={fenetre}
      className="visionneuse"
      aria-label={`Image ${String(indice + 1)} sur ${String(images.length)} : ${image.nom}`}
      onCancel={(e) => {
        e.preventDefault();
        surFermer();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // n'arrête pas la réponse en cours
          e.preventDefault();
          surFermer();
        } else if (plusieurs && e.key === "ArrowRight") aller(1);
        else if (plusieurs && e.key === "ArrowLeft") aller(-1);
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) surFermer(); // clic sur le voile
      }}
    >
      <figure className="visionneuse-cadre">
        <img src={image.dataUrl} alt={image.nom} />
        <figcaption className="visionneuse-legende">
          {image.nom}
          {image.poids ? ` · ${poidsLisible(image.poids)}` : ""}
          {plusieurs ? ` · ${String(indice + 1)}/${String(images.length)}` : ""}
        </figcaption>
      </figure>
      <div className="visionneuse-actions">
        {plusieurs && (
          <button
            type="button"
            className="icone-btn"
            aria-label="Image précédente"
            onClick={() => {
              aller(-1);
            }}
          >
            <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M15 6l-6 6 6 6" />
            </svg>
          </button>
        )}
        {plusieurs && (
          <button
            type="button"
            className="icone-btn"
            aria-label="Image suivante"
            onClick={() => {
              aller(1);
            }}
          >
            <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 6l6 6-6 6" />
            </svg>
          </button>
        )}
        <button type="button" className="icone-btn" aria-label="Fermer l'image" autoFocus onClick={surFermer}>
          <svg className="ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </dialog>
  );
}

export function versAffichees(images: ImageJointe[]): ImageAffichee[] {
  return images.map(({ id, nom, dataUrl, poids }) => ({ id, nom, dataUrl, poids }));
}
