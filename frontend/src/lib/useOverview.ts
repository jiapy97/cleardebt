import { useQuery } from "@tanstack/react-query";
import { api, type Overview } from "./api";

export function useOverview() {
  return useQuery<Overview>({ queryKey: ["overview"], queryFn: api.overview, staleTime: 30_000 });
}

export function useRepoChoices() {
  const { data } = useOverview();
  const choices = data?.repo_choices ?? [];
  const def = choices.find((c) => c.selected)?.key ?? choices[0]?.key ?? "";
  return { choices, def, overview: data };
}
