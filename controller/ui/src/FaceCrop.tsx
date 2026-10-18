import { useEffect, useState } from "react";

export function FaceCrop({ faceId, eyeId, url, placeholder }: {
  faceId: number | null;
  eyeId: number;
  url?: string;
  placeholder: string;
}) {
  const [loaded, setLoaded] = useState<string>();
  const [pending, setPending] = useState(url);
  const [failed, setFailed] = useState<string>();
  useEffect(() => {
    // Finish the current request so frequent telemetry cannot starve a slow load.
    if (!pending && url && url !== loaded && url !== failed) setPending(url);
  }, [url, loaded, pending, failed]);
  const sources = loaded ? [loaded] : [];
  if (pending && pending !== loaded) sources.push(pending);

  return (
    <>
      {sources.map((source) => (
        <img
          key={source}
          src={source}
          alt={source === loaded ? `Face ${faceId} assigned to eye ${eyeId}` : ""}
          aria-hidden={source === loaded ? undefined : true}
          style={source === loaded ? undefined : { display: "none" }}
          onLoad={() => {
            if (source !== pending) return;
            setLoaded(source);
            setPending(undefined);
            setFailed(undefined);
          }}
          onError={() => {
            if (source !== pending) return;
            setFailed(source);
            setPending(undefined);
          }}
        />
      ))}
      {!loaded && <div className="crop-placeholder">{placeholder}</div>}
    </>
  );
}
