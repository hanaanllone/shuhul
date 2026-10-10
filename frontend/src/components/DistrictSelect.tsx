import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { District } from "../lib/types";
import { SelectField } from "./ui";

// Districts that have data, loaded once for whichever page asks.
export function useDistricts(): District[] {
  const [districts, setDistricts] = useState<District[]>([]);

  useEffect(() => {
    api<{ districts: District[] }>("/api/districts")
      .then((data) => setDistricts(data.districts))
      .catch(() => setDistricts([]));
  }, []);

  return districts;
}

interface Props {
  districts: District[];
  value: string;
  onChange: (code: string) => void;
}

export default function DistrictSelect({ districts, value, onChange }: Props) {
  const chosen = districts.find((district) => district.code === value);

  return (
    <SelectField
      label="District"
      value={value}
      onChange={onChange}
      options={
        districts.length
          ? districts.map((district) => ({ value: district.code, label: district.name }))
          : [{ value, label: "Loading..." }]
      }
      hint={
        chosen && !chosen.has_tiles
          ? "This district has the original layers only. Heat, flood and tree canopy are built for Srinagar so far."
          : undefined
      }
    />
  );
}
