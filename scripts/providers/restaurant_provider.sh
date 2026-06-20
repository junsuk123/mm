#!/bin/sh

provider_get_restaurants_by_food() {
  provider_name=$1
  food_name=$2
  location=$3

  case $provider_name in
    mock)
      jq \
        --slurpfile classifications "$PROJECT_ROOT/dataset/restaurant_classifications.json" \
        --arg term "$food_name" \
        --arg location "$location" '
        def classification($category; $food):
          [
            $classifications[0].rules[]
            | . as $rule
            | select(
                (($rule.source_category // $category) == $category)
                and (
                  ($rule.food_pattern == null)
                  or ($food | test($rule.food_pattern))
                )
              )
            | {
                category: $rule.category,
                subcategory: $rule.subcategory
              }
          ][0];
        map(
          . as $restaurant
          | classification(.category; .food) as $class
          | . + $class
          |
          select(
            (.food == $term)
            or (.category == $term)
            or (.subcategory == $term)
            or ((.name // "") | contains($term))
          )
          | . + {
              matched_terms: ([.matched_terms[]?] + [$term] | unique),
              address: (.address // .location // $location),
              roadAddress: (.roadAddress // .address // .location // $location),
              link: (.link // "")
            }
        )
        | sort_by(-(.rating // 0))
        | to_entries
        | map(
            .value + {
              review_rank: (.key + 1),
              walking_minutes: (
                if (.value.distance_m // null) == null then null
                else (((.value.distance_m * 1.25) / 80) | ceil)
                end
              )
            }
          )
      ' "$PROJECT_ROOT/dataset/mock_restaurants.json"
      ;;
    naver)
      naver_get_restaurants_by_food "$food_name" "$location" |
        jq --slurpfile menu "$PROJECT_ROOT/dataset/menu_categories.json" --arg term "$food_name" '
          def selected_main:
            [
              $menu[0]
              | to_entries[]
              | select(.value | index($term))
              | .key
            ][0] // "";
          map(
            . + {
              subcategory: (
                if selected_main != "" then $term else (.subcategory // "") end
              ),
              category: (
                if selected_main != "" then selected_main else .category end
              )
            }
          )
        '
      ;;
    *)
      printf '%s\n' "Unknown provider: $provider_name (use naver)" >&2
      return 1
      ;;
  esac
}
