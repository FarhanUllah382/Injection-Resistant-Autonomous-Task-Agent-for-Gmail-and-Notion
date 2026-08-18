import type { Candidate } from "@/lib/api";
import { getStatusInfo } from "@/lib/candidateStatus";
import styles from "./StatusBadge.module.css";

export default function StatusBadge({ candidate }: { candidate: Candidate }) {
  const info = getStatusInfo(candidate);
  return (
    <span
      className={styles.badge}
      style={{
        background: `var(${info.bgVar})`,
        color: `var(${info.fgVar})`,
      }}
    >
      {info.label}
    </span>
  );
}
