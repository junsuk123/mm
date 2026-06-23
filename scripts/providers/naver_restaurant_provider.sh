#!/bin/sh

naver_get_restaurants_by_food() {
  food_name=$1
  location=$2

  python3 "$PROJECT_ROOT/src/naver_restaurant_api.py" --query "$food_name" --location "$location"
}

naver_get_restaurants_by_terms_file() {
  terms_file=$1
  location=$2

  set -- python3 "$PROJECT_ROOT/src/naver_restaurant_api.py" --location "$location"
  while IFS= read -r food_name; do
    [ -n "$food_name" ] || continue
    set -- "$@" --query "$food_name"
  done < "$terms_file"

  "$@"
}
