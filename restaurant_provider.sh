#!/bin/sh

provider_get_restaurants_by_food() {
  provider_name=$1
  food_name=$2
  location=$3

  case $provider_name in
    mock)
      jq --arg term "$food_name" --arg location "$location" '
        map(
          select(
            (.food == $term)
            or (.category == $term)
            or ((.name // "") | contains($term))
          )
          | . + {
              matched_terms: ([.matched_terms[]?] + [$term] | unique),
              address: (.address // .location // $location),
              roadAddress: (.roadAddress // .address // .location // $location),
              link: (.link // "")
            }
        )
      ' "$SCRIPT_DIR/dataset/mock_restaurants.json"
      ;;
    naver)
      naver_get_restaurants_by_food "$food_name" "$location"
      ;;
    *)
      printf '%s\n' "Unknown provider: $provider_name (use naver)" >&2
      return 1
      ;;
  esac
}
