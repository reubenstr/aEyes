import { useId } from "react";

export function EyePreview({
  opening,
  irisColor = [115, 115, 115],
}: {
  opening: number;
  irisColor?: number[];
}) {
  const id = useId();
  const aperture = 50 * opening;
  return (
    <svg className="eye-shape" viewBox="-2 -2 104 104" aria-hidden="true">
      <defs>
        <clipPath id={`${id}-circle`}>
          <circle cx="50" cy="50" r="50" />
        </clipPath>
        <clipPath id={`${id}-opening`}>
          <ellipse cx="50" cy="50" rx="50" ry={aperture} />
        </clipPath>
        <radialGradient id={`${id}-iris-shade`}>
          <stop offset="55%" stopColor="#121212" stopOpacity="0" />
          <stop offset="100%" stopColor="#121212" stopOpacity="0.4" />
        </radialGradient>
      </defs>
      {/* The eye and opening share one coordinate system, including its margin. */}
      <g clipPath={`url(#${id}-circle)`}>
        <circle cx="50" cy="50" r="50" fill="#353535" />
        {opening > 0 && (
          <g clipPath={`url(#${id}-opening)`}>
            <circle cx="50" cy="50" r="50" fill="#ececec" />
            <circle cx="50" cy="50" r="25" fill={`rgb(${irisColor.join(",")})`} />
            <circle cx="50" cy="50" r="25" fill={`url(#${id}-iris-shade)`} />
            <circle cx="50" cy="50" r="11" fill="#101010" />
            <circle cx="46" cy="45" r="3" fill="#ffffff" fillOpacity="0.61" />
          </g>
        )}
        {opening < 1 && (
          opening > 0
            ? <ellipse cx="50" cy="50" rx="50" ry={aperture} fill="none" stroke="#1b1b1b" strokeWidth="0.8" />
            : <path d="M 0 50 H 100" fill="none" stroke="#1b1b1b" strokeWidth="0.8" />
        )}
      </g>
    </svg>
  );
}
